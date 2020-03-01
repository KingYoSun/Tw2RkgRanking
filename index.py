import sys
sys.path.append('lib/tweepy')

import boto3
import json
import tweepy
import datetime
from boto3.dynamodb.conditions import Key

#自作関数
import functions

#Twitterの認証 
twitter = json.loads(functions.get_secret())
CK = twitter["TWITTER_CK"]
CS = twitter["TWITTER_CS"]
AT = twitter["TWITTER_AT"]
AS = twitter["TWITTER_AS"]

#AWS設定
try:
    #DynamoDB設定
    dynamoDB = boto3.resource('dynamodb', 'ap-northeast-1')
    table = dynamoDB.Table("tweet2rekognition")
    ranking_table = dynamoDB.Table("tweet2rekognition_ranking")
except Exception as e:
    raise('AWS Setup Error: ' + str(e))
finally:
    print('Finish AWS Setup')

#ランキングのアイテム数
max_item = 80
#現在時刻
updated_at = functions.get_update_at()

class DynamoDBTweet:
    def __init__(self):
        self.ranker = []
    
    def get_ranker(self):
        try:
            ranker = ranking_table.query(
                KeyConditionExpression = Key('div').eq(1),
                ScanIndexForward = False,
                Limit = max_item
            )
        except Exception as e:
            print("Loading Ranker list failed: " + str(e))
        else:
            self.ranker = ranker["Items"] if ranker["Count"] > 0 else []
    
    def get_tweet(self):
        today = updated_at["updated_at_date"]
        last_day = today - functions.return_decimal(60*60*24)
        try:
            tweet_list_today = table.query(
                KeyConditionExpression = Key('updated_at_date').eq(today),
                ScanIndexForward = False,
                Limit = max_item
            )
            tweet_list = tweet_list_today["Items"]
            if tweet_list_today["Count"] < max_item:
                additional_load_count = max_item - tweet_list_today["Count"]
                tweet_list_last_day = table.query(
                    KeyConditionExpression = Key('updated_at_date').eq(last_day),
                    ScanIndexForward = False,
                    Limit = additional_load_count
                )
                tweet_list.extend(tweet_list_last_day["Items"])
        except Exception as e:
            print("Loading Tweet from main DB failed: " + str(e))
        else:
            #rateの計算
            for i in range(len(tweet_list)):
                d_fav = tweet_list[i].get("d_fav", 0)
                d_RT = tweet_list[i].get("d_RT", 0)
                tweet_list[i]["rate"] = functions.get_rate(d_fav, d_RT)
                #rankerとtweet_listに被りが無いかチェック
                tweet_list_updated = tweet_list[i]["updated_at_date"] + tweet_list[i]["updated_at_time"]
                if len(self.ranker) > 0:
                    hit_flag = False
                    for j in range(len(self.ranker)):
                        if tweet_list[i]["id"] == self.ranker[j]["id"]:
                            hit_flag = True
                            if tweet_list_updated > (self.ranker[j]["updated_at_date"] + self.ranker[j]["updated_at_time"]) :
                                self.ranker[j] = tweet_list[i]
                            else:
                                break
                    if hit_flag == False :
                        self.ranker.append(tweet_list[i])
                else:
                    #RankerDBリセット時
                    self.ranker.append(tweet_list[i])

class UpdateTweet:
    def __init__(self, ranker):
        self.ranker = ranker
        self.set_twitter_api()
    
    #Twitterオブジェクトの生成
    def set_twitter_api(self):
        try:
            auth = tweepy.OAuthHandler(CK, CS)
            auth.set_access_token(AT, AS)
            self.api = tweepy.API(auth)
        except Exception as e:
            raise('Twitter API Setup Error: ' + str(e))
        finally:
            print('Set Twitter API Object')
    
    #単一ツイートの取得
    def get_tweet_status(self):
        for i in range(len(self.ranker)):
            try:
                result = self.api.get_status(self.ranker[i]["id"])
            except Exception as e:
                raise("get_status Error: " + str(e))
            else:
                self.ranker[i]["favorite"] = functions.return_decimal(result.favorite_count)
                self.ranker[i]["retweet"] = functions.return_decimal(result.retweet_count)
                #最後にupdateされてからの時間
                time_now = updated_at["updated_at_date"] + updated_at["updated_at_time"]
                at_last_updated = self.ranker[i]["updated_at_date"] + self.ranker[i]["updated_at_time"]
                time_last_update = time_now - at_last_updated
                #time_last_updateが一時間(60*60 = 3600)以上の場合、rateの再計算
                if time_last_update > 3600:
                    self.ranker[i]["d_fav"] = self.ranker[i]["favorite"] - self.ranker[i]["past_favorite"]
                    self.ranker[i]["past_favorite"] = self.ranker[i]["favorite"]
                    self.ranker[i]["d_RT"] = self.ranker[i]["retweet"] - self.ranker[i]["past_retweet"]
                    self.ranker[i]["past_retweet"] = self.ranker[i]["retweet"]
                    self.ranker[i]["rate"] = functions.get_rate(self.ranker[i]["d_fav"], self.ranker[i]["d_RT"])

#DynamoDBにデータを送信
class SendDynamoDB:
    def __init__(self, data):
        self.data = data
        
    def put(self):
        try:
            count = 0 # PutTweetCount
            time_to_live = functions.get_24h_after()
            for i in range(len(self.data)):
                #ツイート情報をRanking Tableにput
                ranking_table.put_item(
                    Item = {
                        "div": functions.return_decimal(1),
                        "id": self.data[i]["id"], 
                        "user_name": self.data[i]["user_name"], 
                        "user_screen_name": self.data[i]["user_screen_name"],
                        "user_profile_image": self.data[i]["user_profile_image"],
                        "text": self.data[i]["text"],
                        "hour_count": self.data[i]["hour_count"],
                        "favorite": self.data[i]["favorite"],
                        "past_favorite": self.data[i]["past_favorite"],
                        "d_fav": self.data[i]["d_fav"],
                        "retweet": self.data[i]["retweet"],
                        "past_retweet": self.data[i]["past_retweet"],
                        "d_RT": self.data[i]["d_RT"],
                        "rate": self.data[i]["rate"],
                        "timestamp": self.data[i]["timestamp"],
                        "updated_at_str": updated_at["datetime_str"],
                        "updated_at_date": updated_at["updated_at_date"],
                        "updated_at_time": updated_at["updated_at_time"],
                        "time_to_live": time_to_live,
                        "url": self.data[i]["url"],
                        "img": self.data[i]["img"]
                    }
                )
                count += 1
        except Exception as e:
            print('DynamoDB Error: ' + str(e))
        finally:
            print('Finish putting DynamoDB, put {} Tweet'.format(count))
                
def handler(event, context):
    dynamoDB_tweet = DynamoDBTweet()
    dynamoDB_tweet.get_ranker()
    dynamoDB_tweet.get_tweet()
    update_tweet = UpdateTweet(dynamoDB_tweet.ranker)
    update_tweet.get_tweet_status()
    send_dynamoDB = SendDynamoDB(update_tweet.ranker)
    send_dynamoDB.put()
    #return{
    #    'isBase64Encoded': False,
    #    'statusCode': 200,
    #    'headers': {},
    #    'body':update_tweet.ranker
    #}
