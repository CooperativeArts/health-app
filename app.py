from flask import Flask
from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import TextLoader
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

@app.route('/test')
def test():
    try:
        with open('docs/test.txt', 'r') as file:
            content = file.read()
        return f"File contents: {content}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)