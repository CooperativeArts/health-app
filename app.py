from flask import Flask, request, render_template_string
import os

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
        import openai
        from dotenv import load_dotenv
        
        load_dotenv()
        openai.api_key = os.getenv('OPENAI_API_KEY')
        
        user_question = request.args.get('q', '')
        files = os.listdir('docs')
        all_text = ""
        
        # Get content from PDFs
        for file in files:
            if file.endswith('.pdf'):
                reader = PdfReader(f'docs/{file}')
                for page in reader.pages:
                    all_text += page.extract_text() + "\n\n"
        
        # Ask OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Answer questions based on the provided documents."},
                {"role": "user", "content": f"Based on this document: {all_text[:4000]}\n\nQuestion: {user_question}"}
            ]
        )
        
        return response.choices[0].message['content']
        
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)