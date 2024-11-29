from flask import Flask
import openai
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
openai.api_key = os.getenv('OPENAI_API_KEY')

@app.route('/')
def hello():
    return 'Hello, World!'

@app.route('/test')
def test():
    return "Basic test route!"  # Added exclamation mark

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)