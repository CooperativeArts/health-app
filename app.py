from flask import Flask, request, render_template
from langchain.chat_models import ChatOpenAI
from langchain.embeddings.openai import OpenAIEmbeddings
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables

app = Flask(__name__)
llm = ChatOpenAI()
embeddings = OpenAIEmbeddings()

@app.route('/')
def hello():
    return 'Hello, World!'

@app.route('/test')
def test():
    try:
        response = llm.predict("Say hello!")
        return f"OpenAI is working! Response: {response}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)