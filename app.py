from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv

[Previous HTML_TEMPLATE stays the same...]

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
        
        # Get current working directory and full path to docs
        cwd = os.getcwd()
        docs_path = os.path.join(cwd, 'docs')
        
        # List all PDF files
        files = [f for f in os.listdir(docs_path) if f.endswith('.pdf')]
        
        all_text = ""
        total_size = 0
        max_size = 15000  # Increased significantly
        files_read = []

        # If user asks about specific file, prioritize it
        specific_file = None
        for file in files:
            if file.lower() in user_question.lower():
                specific_file = file
                files.remove(file)
                files.insert(0, file)  # Put it first

        for file in files:
            try:
                reader = PdfReader(os.path.join(docs_path, file))
                file_content = f"\n=== Start of {file} ===\n"
                
                # Read more pages if it's the specifically requested file
                pages_to_read = 5 if file == specific_file else 2
                
                for page_num, page in enumerate(reader.pages[:pages_to_read]):
                    page_text = page.extract_text()
                    if total_size + len(page_text) < max_size:
                        file_content += f"[Page {page_num + 1}]: {page_text}\n"
                        total_size += len(page_text)
                    else:
                        if file == specific_file:
                            # For specific file, clear some space
                            all_text = all_text[:max_size//2]  # Keep only half of previous content
                            total_size = len(all_text)
                            file_content += f"[Page {page_num + 1}]: {page_text}\n"
                            total_size += len(page_text)
                        else:
                            break
                
                file_content += f"=== End of {file} ===\n\n"
                all_text += file_content
                files_read.append(file)
                
            except Exception as e:
                print(f"Error reading {file}: {str(e)}")
                continue

        if not all_text.strip():
            return "Error: No content could be read from the documents."

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": """You are analyzing PDF documents. You have access to content from multiple files.
                When answering questions:
                1. Use only the content actually provided in the text
                2. Cite specific documents and page numbers
                3. If you're asked about a specific document but don't see its content, mention that
                4. If you find relevant information, quote it directly"""},
                {"role": "user", "content": f"""Here is content from multiple documents:

{all_text}

Question: {user_question}

Please answer based only on the content provided above. If asked about a specific document, prioritize information from that document."""}
            ],
            temperature=0
        )
        
        return response.choices[0].message['content']
        
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)