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
        
        app.logger.info("Starting query process")
        load_dotenv()
        openai.api_key = os.getenv('OPENAI_API_KEY')
        
        user_question = request.args.get('q', '')
        app.logger.info(f"Got question: {user_question}")
        
        files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
        app.logger.info(f"Found {len(files)} PDF files")
        
        all_documents = []
        for file in files:
            try:
                app.logger.info(f"Reading {file}")
                reader = PdfReader(f'docs/{file}')
                file_text = ""
                for page in reader.pages:
                    file_text += page.extract_text() + "\n"
                all_documents.append({"name": file, "content": file_text})
                app.logger.info(f"Successfully read {file}")
            except Exception as e:
                app.logger.error(f"Error reading {file}: {str(e)}")
                continue
        
        combined_text = ""
        for doc in all_documents:
            combined_text += f"\nFrom {doc['name']}:\n{doc['content']}\n"
            
        app.logger.info(f"Processed {len(all_documents)} documents")
        
        # Ask OpenAI using combined text
        app.logger.info("Sending to OpenAI")
        response = openai.ChatCompletion.create(
    model="gpt-4",  # Changed from gpt-3.5-turbo to gpt-4
    messages=[
        {"role": "system", "content": "You are a highly knowledgeable assistant analyzing multiple documents. Provide detailed, accurate answers and cite which specific documents contain the information you're referencing. If information appears in multiple documents, mention all relevant sources."},
        {"role": "user", "content": f"Based on these documents:\n{combined_text[:15000]}\n\nQuestion: {user_question}"}
    ],
    temperature=0  # Added for more precise responses
)
        
        answer = response.choices[0].message['content']
        app.logger.info("Got response from OpenAI")
        return answer
        
    except Exception as e:
        app.logger.error(f"Error occurred: {str(e)}")
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)