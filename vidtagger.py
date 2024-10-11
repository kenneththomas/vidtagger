from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
import os
from sqlalchemy import desc, func

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///videos.db'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
db = SQLAlchemy(app)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_filepath = db.Column(db.String(255), nullable=False)
    stored_filepath = db.Column(db.String(255), nullable=False)
    nickname = db.Column(db.String(100))
    description = db.Column(db.Text)
    tags = db.Column(db.String(255))

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    videos = Video.query.order_by(desc(Video.id)).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('index.html', videos=videos.items, page=page, total_pages=videos.pages)

@app.route('/add', methods=['GET', 'POST'])
def add_video():
    if request.method == 'POST':
        file = request.files.get('file')
        nickname = request.form.get('nickname')
        description = request.form.get('description')
        tags = request.form.get('tags')
        
        if not file:
            return jsonify({"error": "No file provided"}), 400
        
        original_filepath = file.filename
        filename = os.path.basename(original_filepath)
        stored_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(stored_filepath)
            new_video = Video(original_filepath=original_filepath, 
                              stored_filepath=stored_filepath,
                              nickname=nickname, 
                              description=description, 
                              tags=tags)
            db.session.add(new_video)
            db.session.commit()
            return jsonify({"success": True}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    # Get existing tags for GET request
    tags = db.session.query(
        func.trim(func.lower(func.substr(Video.tags, 1, func.instr(Video.tags + ',', ',') - 1))).cast(db.String).label('tag'),
        func.count('*').label('count')
    ).group_by('tag').order_by(desc('count')).all()
    
    return render_template('add.html', existing_tags=tags)

@app.route('/play/<int:video_id>')
def play_video(video_id):
    video = Video.query.get_or_404(video_id)
    
    if os.path.isfile(video.stored_filepath):
        # Open the video with the default video player
        # subprocess.Popen(['xdg-open', video.stored_filepath])  # For Linux
        # subprocess.Popen(['open', video.stored_filepath])  # For macOS
        os.startfile(video.stored_filepath)  # For Windows
    else:
        return "Video file not found.", 404
    
    return redirect(url_for('index'))

@app.route('/filter')
def filter_videos():
    tag = request.args.get('tag')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    if tag:
        videos = Video.query.filter(Video.tags.contains(tag)).order_by(desc(Video.id))
    else:
        videos = Video.query.order_by(desc(Video.id))

    paginated_videos = videos.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('index.html', 
                           videos=paginated_videos.items, 
                           page=page, 
                           total_pages=paginated_videos.pages,
                           tag=tag)

@app.route('/delete/<int:video_id>', methods=['POST'])
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    try:
        # Delete the file
        if os.path.exists(video.stored_filepath):
            os.remove(video.stored_filepath)
        
        # Delete the database entry
        db.session.delete(video)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/edit_tags/<int:video_id>', methods=['POST'])
def edit_tags(video_id):
    video = Video.query.get_or_404(video_id)
    new_tags = request.form.get('tags')
    
    try:
        video.tags = new_tags
        db.session.commit()
        return jsonify({"success": True, "new_tags": new_tags}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/video/<int:video_id>')
def video_detail(video_id):
    video = Video.query.get_or_404(video_id)
    return render_template('video_detail.html', video=video)

@app.route('/edit_description/<int:video_id>', methods=['POST'])
def edit_description(video_id):
    video = Video.query.get_or_404(video_id)
    new_description = request.form.get('description')
    
    try:
        video.description = new_description
        db.session.commit()
        return jsonify({"success": True, "new_description": new_description}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/get_tags')
def get_tags():
    tags = db.session.query(
        func.trim(func.lower(func.substr(Video.tags, 1, func.instr(Video.tags + ',', ',') - 1))).cast(db.String).label('tag'),
        func.count('*').label('count')
    ).group_by('tag').order_by(desc('count')).all()
    
    return jsonify([{'tag': tag, 'count': count} for tag, count in tags])

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run("0.0.0.0", 5015, debug=True)
