from flask import Flask
from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import DirectoryLoader
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
llm = ChatOpenAI()

@app.route('/')
def hello():
    return f"Current directory: {os.getcwd()}"

@app.route('/test')
def test():
    try:
        current_dir = os.getcwd()
        files = os.listdir('docs')
        return f"Directory: {current_dir}, Files in docs: {files}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)