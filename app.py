from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv

app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>RAG Chat</title>
    <style>
        body { max-width: 800px; margin: auto; padding: 20px; }
        #chat-box { height: 400px; border: 1px solid #ccc; overflow-y: scroll; margin: 20px 0; padding: 10px; }
        input[type="text"] { width: 80%; padding: 10px; }
        button { padding: 10px 20px; }
        .loading { color: #666; }
    </style>
</head>
<body>
    <h1>Document Q&A</h1>
    <div id="chat-box"></div>
    <form id="chat-form">
        <input type="text" id="question" placeholder="Ask a question..." required>
        <button type="submit" id="submit-btn">Send</button>
    </form>
    <script>
        document.getElementById('chat-form').onsubmit = async function(e) {
            e.preventDefault();
            const chatBox = document.getElementById('chat-box');
            const question = document.getElementById('question').value;
            const submitBtn = document.getElementById('submit-btn');
            
            submitBtn.disabled = true;
            chatBox.innerHTML += '<p><b>Q:</b> ' + question + '</p>';
            chatBox.innerHTML += '<p class="loading">Loading...</p>';
            chatBox.scrollTop = chatBox.scrollHeight;
            
            try {
                const response = await fetch('/query?q=' + encodeURIComponent(question));
                const answer = await response.text();
                chatBox.removeChild(chatBox.lastChild);
                chatBox.innerHTML += '<p><b>A:</b> ' + answer + '</p>';
            } catch (error) {
                chatBox.removeChild(chatBox.lastChild);
                chatBox.innerHTML += '<p style="color: red;"><b>Error:</b> ' + error.message + '</p>';
            } finally {
                submitBtn.disabled = false;
                document.getElementById('question').value = '';
                chatBox.scrollTop = chatBox.scrollHeight;
            }
        };
    </script>
</body>
</html>
'''

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/query')
def query():
    try:
        from pypdf import PdfReader
        
        load_dotenv()
        openai.api_key = os.getenv('OPENAI_API_KEY')
        
        user_question = request.args.get('q', '')
        files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
        
        # Read content from all files
        all_text = ""
        max_chars = 15000

        for file in files:
            try:
                reader = PdfReader(f'docs/{file}')
                file_text = f"\n=== Document: {file} ===\n"
                
                # Get first 3 pages of each document
                for i, page in enumerate(reader.pages[:3]):
                    file_text += f"[Page {i+1}]: {page.extract_text()}\n"
                    
                all_text += file_text + "\n"
                
                # If we exceed max chars, keep the latest content
                if len(all_text) > max_chars:
                    all_text = all_text[-max_chars:]
                    
            except Exception as e:
                continue

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are analyzing PDF documents. Provide information only from the content shown. If you see a document name but no content, mention that."},
                {"role": "user", "content": f"Documents content:\n{all_text}\n\nQuestion: {user_question}"}
            ],
            temperature=0
        )
        
        return response.choices[0].message['content']
        
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)