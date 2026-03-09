import boto3
import os
from botocore.client import Config
from dotenv import load_dotenv

load_dotenv()
S3_REGION = os.environ.get('S3_REGION', 'ap-northeast-2')
s3_client = boto3.client(
    's3',
    endpoint_url=f'https://s3.{S3_REGION}.amazonaws.com',
    region_name=S3_REGION,
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    config=Config(signature_version='s3v4')
)
url = s3_client.generate_presigned_url(
    'get_object',
    Params={'Bucket': os.environ.get('S3_BUCKET'), 'Key': 'video/source/face_0001.mp4'},
    ExpiresIn=3600
)
print(url)
