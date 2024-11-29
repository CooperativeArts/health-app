from flask import Flask
from langchain.chat_models import ChatOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

@app.route('/')
def hello():
    return 'Hello, World!'

@app.route('/test')
def test():
    try:
        llm = ChatOpenAI()  # Move this inside the function
        return "OpenAI setup working!"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)