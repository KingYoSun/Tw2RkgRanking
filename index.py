import sys
sys.path.append('lib/tweepy')

import boto3
import json
import tweepy
import datetime
from boto3.dynamodb.conditions import Key
from decimal import Decimal, ROUND_DOWN

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
max_item = 100

class DynamoDBTweet:
    def __init__(self):
        self.ranker = []
        self.load_count = 0
    
    def get_ranker(self):
        try:
            ranker = ranking_table.query(
                KeyConditionExpression = Key('div').eq(1),
                ScanIndexForward = False
            )
        except Exception as e:
            print("Loading Ranker list failed: " + str(e))
        else:
            self.ranker = ranker["Items"]
    
    def get_tweet(self, maxItems):
        updated_at = functions.get_update_at() 
        today = updated_at["updated_at_date"]
        last_day = today - Decimal(60*60*24)
        self.load_count = maxItems - len(self.ranker)
        try:
            tweet_list_today = table.query(
                KeyConditionExpression = Key('updated_at_date').eq(today),
                ScanIndexForward = False,
                Limit = self.load_count
            )
            tweet_list = tweet_list_today["Items"]
            if tweet_list_today["Count"] < self.load_count:
                additional_load_count = self.load_count - tweet_list_today["Count"]
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
            self.ranker.extend(tweet_list)
    
    def sort_ranker(self):
        self.ranker = sorted(self.ranker, key=lambda x:x["rate"], reverse=True)

class GetTweet:
    def __init__(self):
        self.tweet_data = []
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
    def get_tweet_status(self, id):
        try:
            result = self.api.get_status(id)
        except Exception as e:
            raise("get_status Error: " + str(e))
        else:
            return result
    

def handler(event, context):
    dynamoDB_tweet = DynamoDBTweet()
    dynamoDB_tweet.get_ranker()
    if len(dynamoDB_tweet.ranker) < max_item:
        dynamoDB_tweet.get_tweet(max_item)
    dynamoDB_tweet.sort_ranker()
    return{
        'isBase64Encoded': False,
        'statusCode': 200,
        'headers': {},
        'body': dynamoDB_tweet.ranker
    }
