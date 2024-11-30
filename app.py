from flask import Flask
from langchain.chat_models import ChatOpenAI
from langchain.document_loaders import TextLoader
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
llm = ChatOpenAI()

@app.route('/')
def hello():
    return 'Hello, World!'

@app.route('/test')
def test():
    try:
        loader = TextLoader("docs/test.txt")
        docs = loader.load()
        content = docs[0].page_content if docs else "No content found"
        return f"Document content: {content}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)