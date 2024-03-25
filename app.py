import os

import boto3
import uuid

from botocore.exceptions import ClientError
from flask import Flask, jsonify, make_response, request
from werkzeug.utils import secure_filename

app = Flask(__name__)


dynamodb_client = boto3.client('dynamodb')

if os.environ.get('IS_OFFLINE'):
    dynamodb_client = boto3.client(
        'dynamodb', region_name='localhost', endpoint_url='http://localhost:8000'
    )

s3_client = boto3.client('s3')
textract_client = boto3.client('textract')

USERS_TABLE = os.environ['USERS_TABLE']
FILES_TABLE = os.environ['FILES_TABLE']

S3_BUCKET_NAME = os.environ.get('MY_S3_BUCKET', 'text-extractor-bucket')


@app.route('/users/<string:user_id>')
def get_user(user_id):
    result = dynamodb_client.get_item(
        TableName=USERS_TABLE, Key={'userId': {'S': user_id}}
    )
    item = result.get('Item')
    if not item:
        return jsonify({'error': 'Could not find user with provided "userId"'}), 404

    return jsonify(
        {'userId': item.get('userId').get('S'), 'name': item.get('name').get('S')}
    )


@app.route('/users', methods=['POST'])
def create_user():
    user_id = request.json.get('userId')
    name = request.json.get('name')
    if not user_id or not name:
        return jsonify({'error': 'Please provide both "userId" and "name"'}), 400

    dynamodb_client.put_item(
        TableName=USERS_TABLE, Item={'userId': {'S': user_id}, 'name': {'S': name}}
    )

    return jsonify({'userId': user_id, 'name': name})


@app.route('/files', methods=['POST'])
def upload_file():
    callback_url = request.json.get('callback_url')
    if not callback_url:
        return jsonify({'error': 'Please provide a callback URL'}), 400

    file_id = str(uuid.uuid4())
    filename = file_id + ".pdf"

    if not filename or not allowed_file(filename):
        return jsonify({'error': 'Invalid file type'}), 400
    # Generate a pre-signed URL for uploading to S3
    upload_url = s3_client.generate_presigned_url(
        ClientMethod='put_object',
        Params={'Bucket': S3_BUCKET_NAME, 'Key': filename},
        ExpiresIn=3600  # One hour expiration
    )

    dynamodb_client.put_item(
        TableName=FILES_TABLE, Item={'fileId': {'S': file_id}, 'upload_url': {'S': upload_url}, 'callback_url': {'S': callback_url}}
    )

    return jsonify({'fileId': file_id, 'upload_url': upload_url, 'callback_url': callback_url})


@app.route('/files/<string:file_id>')
def get_file_info(file_id):
    result = dynamodb_client.get_item(
        TableName=FILES_TABLE, Key={'fileId': {'S': file_id}}
    )
    item = result.get('Item')
    if not item:
        return jsonify({'error': 'Could not find file with provided "fileId"'}), 404

    return jsonify(
        {'fileId': item.get('fileId').get('S'), 'upload_url': item.get('upload_url').get('S'), 'callback_url': item.get('callback_url').get('S')}
    )


@app.errorhandler(404)
def resource_not_found(e):
    return make_response(jsonify(error='Not found!'), 404)


def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpeg', 'tiff'}
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
