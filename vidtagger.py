from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, Response, make_response
from flask_sqlalchemy import SQLAlchemy
import os
from sqlalchemy import desc, func
import re
from werkzeug.utils import secure_filename
import ffmpeg
from PIL import Image
import io
from werkzeug.datastructures import FileStorage
from datetime import datetime
import uuid
import random
import string

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///videos.db'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
app.config['STEALTH_UPLOAD_FOLDER'] = os.path.join(app.root_path, 'stealth_uploads')
db = SQLAlchemy(app)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_filepath = db.Column(db.String(255), nullable=False)
    stored_filepath = db.Column(db.String(255), nullable=False)
    nickname = db.Column(db.String(100))
    description = db.Column(db.Text)
    tags = db.Column(db.String(255))
    thumbnail_path = db.Column(db.String(255))  # New field for thumbnail
    view_count = db.Column(db.Integer, default=0)  # New field for view count
    likes = db.Column(db.Integer, default=0)  # Add this line
    playlists = db.relationship('Playlist', secondary='playlist_video',
                                 backref=db.backref('videos', lazy='dynamic'))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    likes = db.Column(db.Integer, default=0)  # Add this line

class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PlaylistVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlist.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # For ordering videos in playlist

def convert_webm_to_mp4(input_path):
    """Convert WebM file to MP4 and return the new filepath"""
    output_path = os.path.splitext(input_path)[0] + '.mp4'
    try:
        (
            ffmpeg
            .input(input_path)
            .output(output_path, acodec='aac', vcodec='h264', **{'b:v': '2M'})
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        os.remove(input_path)  # Remove original WebM file
        return output_path
    except ffmpeg.Error as e:
        print(f"Error converting WebM to MP4: {e.stderr.decode()}")
        raise

def generate_unique_filename(original_filename, upload_folder):
    """Generate a unique filename by adding timestamp and random string if needed"""
    name, ext = os.path.splitext(original_filename)
    filename = secure_filename(name + ext)
    filepath = os.path.join(upload_folder, filename)
    
    # If file already exists, add timestamp and random string
    if os.path.exists(filepath):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        filename = secure_filename(f"{name}_{timestamp}_{random_string}{ext}")
        filepath = os.path.join(upload_folder, filename)
    
    return filename, filepath

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'newest')  # Default sort by newest
    per_page = 10

    # Create base query
    query = Video.query

    # Apply sorting
    if sort_by == 'newest':
        query = query.order_by(desc(Video.id))
    elif sort_by == 'oldest':
        query = query.order_by(Video.id)
    elif sort_by == 'most_viewed':
        query = query.order_by(desc(Video.view_count))
    elif sort_by == 'most_liked':
        query = query.order_by(desc(Video.likes))

    videos = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('index.html', 
                         videos=videos.items, 
                         page=page, 
                         total_pages=videos.pages, 
                         tag=None,
                         sort_by=sort_by)

@app.route('/add', methods=['GET', 'POST'])
def add_video():
    if request.method == 'POST':
        file = request.files.get('file')
        nickname = request.form.get('nickname')
        description = request.form.get('description')
        tags = request.form.get('tags')
        stealth = request.form.get('stealth') == 'on'
        
        if not nickname and tags:
            nickname = ' '.join(tag.strip() for tag in tags.split(','))
        
        if not file:
            return jsonify({"error": "No file provided"}), 400
        
        original_filepath = file.filename
        original_extension = os.path.splitext(original_filepath)[1]
        
        if nickname:
            base_filename = secure_filename(nickname + original_extension)
        else:
            base_filename = secure_filename(original_filepath)
        
        upload_folder = app.config['STEALTH_UPLOAD_FOLDER'] if stealth else app.config['UPLOAD_FOLDER']
        new_filename, stored_filepath = generate_unique_filename(base_filename, upload_folder)
        
        try:
            os.makedirs(upload_folder, exist_ok=True)
            file.save(stored_filepath)
            
            # Convert WebM to MP4 if necessary
            if original_extension == '.webm':
                stored_filepath = convert_webm_to_mp4(stored_filepath)
                new_filename = os.path.basename(stored_filepath)
            
            # Generate thumbnail
            thumbnail_filename = f"thumbnail_{os.path.splitext(new_filename)[0]}.jpg"
            thumbnails_dir = os.path.join(app.static_folder, 'thumbnails')
            os.makedirs(thumbnails_dir, exist_ok=True)
            thumbnail_path = os.path.join(thumbnails_dir, thumbnail_filename)
            
            # Get video duration more robustly
            probe = ffmpeg.probe(stored_filepath)
            duration = None
            # Try different methods to get duration
            for stream in probe['streams']:
                if 'duration' in stream:
                    duration = float(stream['duration'])
                    break
            
            # If duration not found in streams, try format
            if duration is None and 'format' in probe and 'duration' in probe['format']:
                duration = float(probe['format']['duration'])
            
            # If still no duration, use a default timestamp
            if duration is None:
                duration = 0
            
            # Extract middle frame
            (
                ffmpeg
                .input(stored_filepath, ss=duration/2 if duration > 0 else 0)
                .filter('scale', 320, -1)
                .output(thumbnail_path, vframes=1)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            
            # Set the thumbnail_path to be relative to the static folder
            relative_thumbnail_path = os.path.join('thumbnails', thumbnail_filename).replace('\\', '/')
            
            new_video = Video(original_filepath=original_filepath, 
                              stored_filepath=stored_filepath,
                              nickname=nickname, 
                              description=description, 
                              tags=tags,
                              thumbnail_path=relative_thumbnail_path,
                              view_count=0)  # Initialize view_count to 0
            db.session.add(new_video)
            db.session.commit()
            
            return jsonify({"success": True, "video_id": new_video.id}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    # Replace the existing tags query with a query for recent tags
    recent_tags = db.session.query(
        Video.tags, Video.id
    ).order_by(
        desc(Video.id)  # Order by most recent videos first
    ).limit(20).all()  # Get tags from last 20 videos
    
    # Process the tags to get unique recent tags
    processed_tags = []
    seen_tags = set()
    
    for video_tags, _ in recent_tags:
        if video_tags:  # Check if tags exist
            tags_list = [tag.strip() for tag in video_tags.split(',')]
            for tag in tags_list:
                if tag and tag.lower() not in seen_tags:  # Avoid duplicates
                    seen_tags.add(tag.lower())
                    processed_tags.append(tag)
    
    return render_template('add.html', recent_tags=processed_tags[:20])

@app.route('/stream/<int:video_id>')
def stream_video(video_id):
    video = Video.query.get_or_404(video_id)
    
    # Determine mime type based on file extension
    file_extension = os.path.splitext(video.stored_filepath)[1].lower()
    mime_type = 'video/webm' if file_extension == '.webm' else 'video/mp4'
    
    range_header = request.headers.get('Range', None)
    file_size = os.path.getsize(video.stored_filepath)

    if range_header:
        byte1, byte2 = 0, None
        match = re.search(r'(\d+)-(\d*)', range_header)
        groups = match.groups()

        if groups[0]:
            byte1 = int(groups[0])
        if groups[1]:
            byte2 = int(groups[1])

        if byte2 is None:
            byte2 = file_size - 1
        length = byte2 - byte1 + 1

        with open(video.stored_filepath, 'rb') as f:
            f.seek(byte1)
            data = f.read(length)

        resp = make_response(data)
        resp.headers.set('Content-Type', mime_type)  # Use dynamic mime type
        resp.headers.set('Content-Range', f'bytes {byte1}-{byte2}/{file_size}')
        resp.headers.set('Accept-Ranges', 'bytes')
        resp.headers.set('Content-Length', str(length))
        return resp, 206
    else:
        return send_file(video.stored_filepath, mimetype=mime_type)  # Use dynamic mime type

@app.route('/filter')
def filter_videos():
    tag = request.args.get('tag')
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'newest')  # Default sort by newest
    per_page = 10

    # Create base query
    query = Video.query

    # Apply tag filter
    if tag:
        query = query.filter(Video.tags.contains(tag))

    # Apply sorting
    if sort_by == 'newest':
        query = query.order_by(desc(Video.id))
    elif sort_by == 'oldest':
        query = query.order_by(Video.id)
    elif sort_by == 'most_viewed':
        query = query.order_by(desc(Video.view_count))
    elif sort_by == 'most_liked':
        query = query.order_by(desc(Video.likes))

    paginated_videos = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('index.html', 
                         videos=paginated_videos.items, 
                         page=page, 
                         total_pages=paginated_videos.pages,
                         tag=tag,
                         sort_by=sort_by)

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

def get_related_videos(current_video, limit=8):
    if not current_video.tags:
        return []
    
    current_tags = set(tag.strip().lower() for tag in current_video.tags.split(',') if tag.strip())
    
    # Get all videos except the current one
    other_videos = Video.query.filter(Video.id != current_video.id).all()
    
    # Calculate similarity scores
    video_scores = []
    for video in other_videos:
        if video.tags:
            video_tags = set(tag.strip().lower() for tag in video.tags.split(',') if tag.strip())
            common_tags = len(current_tags.intersection(video_tags))
            if common_tags > 0:
                video_scores.append((video, common_tags))
    
    # Sort by number of common tags (descending)
    video_scores.sort(key=lambda x: x[1], reverse=True)
    
    # Return the top N videos
    return [video for video, score in video_scores[:limit]]

@app.route('/video/<int:video_id>')
def video_detail(video_id):
    video = Video.query.get_or_404(video_id)
    if video.view_count is None:
        video.view_count = 1
    else:
        video.view_count += 1
    
    related_videos = get_related_videos(video)
    comments = Comment.query.filter_by(video_id=video_id).order_by(Comment.timestamp.desc()).all()
    db.session.commit()
    return render_template('video_detail.html', video=video, related_videos=related_videos, comments=comments)

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

@app.route('/get_tag_suggestions')
def get_tag_suggestions():
    query = request.args.get('q', '').lower()
    all_tags = db.session.query(
        func.trim(func.lower(func.substr(Video.tags, 1, func.instr(Video.tags + ',', ',') - 1))).label('tag')
    ).distinct().all()
    
    # Filter out None values and then check for matches
    matching_tags = [tag[0] for tag in all_tags if tag[0] is not None and query in tag[0].lower()]
    matching_tags.sort(key=lambda x: x.lower().index(query))  # Sort by relevance
    return jsonify(matching_tags[:10])  # Return top 10 matches

@app.route('/thumbnail/<int:video_id>')
def serve_thumbnail(video_id):
    video = Video.query.get_or_404(video_id)
    thumbnail_path = os.path.join(app.static_folder, video.thumbnail_path)
    return send_file(thumbnail_path, mimetype='image/jpeg')

@app.route('/increment_view/<int:video_id>', methods=['POST'])
def increment_view(video_id):
    video = Video.query.get_or_404(video_id)
    if video.view_count is None:
        video.view_count = 1
    else:
        video.view_count += 1
    db.session.commit()
    return jsonify({"success": True, "new_view_count": video.view_count})

@app.route('/bulk_upload', methods=['GET', 'POST'])
def bulk_upload():
    if request.method == 'POST':
        uploaded_files = request.files.getlist('files')
        
        if not uploaded_files:
            return jsonify({"error": "No files provided"}), 400
        
        successful_uploads = 0
        errors = []

        for file in uploaded_files:
            if isinstance(file, FileStorage) and file.filename != '':
                original_extension = os.path.splitext(file.filename)[1].lower()
                if original_extension not in ['.mp4', '.webm']:
                    errors.append(f"Skipped {file.filename}: Only MP4 and WebM files are allowed")
                    continue

                try:
                    new_filename, stored_filepath = generate_unique_filename(
                        file.filename, 
                        app.config['STEALTH_UPLOAD_FOLDER']
                    )
                    
                    os.makedirs(app.config['STEALTH_UPLOAD_FOLDER'], exist_ok=True)
                    file.save(stored_filepath)
                    
                    # Convert WebM to MP4 if necessary
                    if original_extension == '.webm':
                        stored_filepath = convert_webm_to_mp4(stored_filepath)
                        new_filename = os.path.basename(stored_filepath)

                    # Generate thumbnail
                    thumbnail_filename = f"thumbnail_{os.path.splitext(new_filename)[0]}.jpg"
                    thumbnails_dir = os.path.join(app.static_folder, 'thumbnails')
                    os.makedirs(thumbnails_dir, exist_ok=True)
                    thumbnail_path = os.path.join(thumbnails_dir, thumbnail_filename)
                    
                    # Get video duration more robustly
                    probe = ffmpeg.probe(stored_filepath)
                    duration = None
                    # Try different methods to get duration
                    for stream in probe['streams']:
                        if 'duration' in stream:
                            duration = float(stream['duration'])
                            break
                    
                    # If duration not found in streams, try format
                    if duration is None and 'format' in probe and 'duration' in probe['format']:
                        duration = float(probe['format']['duration'])
                    
                    # If still no duration, use a default timestamp
                    if duration is None:
                        duration = 0
                    
                    # Extract middle frame
                    (
                        ffmpeg
                        .input(stored_filepath, ss=duration/2 if duration > 0 else 0)
                        .filter('scale', 320, -1)
                        .output(thumbnail_path, vframes=1)
                        .overwrite_output()
                        .run(capture_stdout=True, capture_stderr=True)
                    )
                    
                    # Set the thumbnail_path to be relative to the static folder
                    relative_thumbnail_path = os.path.join('thumbnails', thumbnail_filename).replace('\\', '/')
                    
                    new_video = Video(original_filepath=file.filename, 
                                      stored_filepath=stored_filepath,
                                      thumbnail_path=relative_thumbnail_path,
                                      view_count=0)
                    db.session.add(new_video)
                    successful_uploads += 1
                except Exception as e:
                    errors.append(f"Error uploading {file.filename}: {str(e)}")
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "uploaded": successful_uploads,
            "errors": errors
        }), 200

    return render_template('bulk_upload.html')

@app.route('/cleanup_stealth', methods=['POST'])
def cleanup_stealth():
    try:
        # Get all videos in stealth folder
        stealth_videos = Video.query.filter(
            Video.stored_filepath.like(f"{app.config['STEALTH_UPLOAD_FOLDER']}%")
        ).all()
        
        deleted_count = 0
        for video in stealth_videos:
            # Check if file exists
            if not os.path.exists(video.stored_filepath):
                # Delete thumbnail if it exists
                if video.thumbnail_path:
                    thumbnail_path = os.path.join(app.static_folder, video.thumbnail_path)
                    if os.path.exists(thumbnail_path):
                        os.remove(thumbnail_path)
                
                # Delete database entry
                db.session.delete(video)
                deleted_count += 1
        
        db.session.commit()
        return jsonify({
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Cleaned up {deleted_count} missing video entries"
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/like/<int:video_id>', methods=['POST'])
def like_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.likes is None:
        video.likes = 1
    else:
        video.likes += 1
    db.session.commit()
    return jsonify({"success": True, "new_like_count": video.likes})

@app.route('/add_comment/<int:video_id>', methods=['POST'])
def add_comment(video_id):
    video = Video.query.get_or_404(video_id)
    author = request.form.get('author', '').strip()
    content = request.form.get('content', '').strip()
    
    if not author or not content:
        return jsonify({"error": "Name and comment are required"}), 400
    
    try:
        comment = Comment(
            video_id=video_id,
            author=author,
            content=content,
            likes=0
        )
        db.session.add(comment)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "comment": {
                "id": comment.id,
                "author": comment.author,
                "content": comment.content,
                "timestamp": comment.timestamp.strftime("%m/%d/%Y %I:%M %p"),
                "likes": comment.likes
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/like_comment/<int:comment_id>', methods=['POST'])
def like_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.likes is None:
        comment.likes = 1
    else:
        comment.likes += 1
    db.session.commit()
    return jsonify({"success": True, "new_like_count": comment.likes})

@app.route('/edit_title/<int:video_id>', methods=['POST'])
def edit_title(video_id):
    video = Video.query.get_or_404(video_id)
    new_title = request.json.get('title', '').strip()

    if not new_title:
        return jsonify({"error": "Title cannot be empty"}), 400

    try:
        video.nickname = new_title
        db.session.commit()
        return jsonify({"success": True, "new_title": new_title}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/move_to_regular/<int:video_id>', methods=['POST'])
def move_to_regular(video_id):
    video = Video.query.get_or_404(video_id)
    
    # Check if video is in stealth folder
    if not video.stored_filepath.startswith(app.config['STEALTH_UPLOAD_FOLDER']):
        return jsonify({"error": "Video is not in stealth uploads"}), 400
        
    try:
        # Create new filepath in regular uploads
        filename = os.path.basename(video.stored_filepath)
        new_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Move the file
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.rename(video.stored_filepath, new_filepath)
        
        # Update database
        video.stored_filepath = new_filepath
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Video moved to regular uploads"
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/create_playlist', methods=['POST'])
def create_playlist():
    name = request.form.get('name')
    description = request.form.get('description', '')
    video_id = request.form.get('video_id')
    
    if not name:
        return jsonify({"error": "Playlist name is required"}), 400
        
    try:
        # Create the playlist first
        playlist = Playlist(name=name, description=description)
        db.session.add(playlist)
        db.session.flush()  # This assigns the ID to the playlist object
        
        # If video_id is provided, add it to the playlist
        if video_id:
            try:
                video_id = int(video_id)
                playlist_video = PlaylistVideo(
                    playlist_id=playlist.id,
                    video_id=video_id,
                    position=1
                )
                db.session.add(playlist_video)
            except ValueError:
                print(f"Invalid video_id: {video_id}")
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "playlist_id": playlist.id,
            "name": playlist.name
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error creating playlist: {str(e)}")  # Debug log
        return jsonify({"error": str(e)}), 500

@app.route('/add_to_playlist/<int:playlist_id>/<int:video_id>', methods=['POST'])
def add_to_playlist(playlist_id, video_id):
    try:
        # Get the last position in the playlist
        last_position = db.session.query(func.max(PlaylistVideo.position))\
            .filter_by(playlist_id=playlist_id).scalar() or 0
            
        playlist_video = PlaylistVideo(
            playlist_id=playlist_id,
            video_id=video_id,
            position=last_position + 1
        )
        db.session.add(playlist_video)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/get_playlist/<int:playlist_id>')
def get_playlist(playlist_id):
    playlist = Playlist.query.get_or_404(playlist_id)
    videos = db.session.query(Video, PlaylistVideo)\
        .join(PlaylistVideo)\
        .filter(PlaylistVideo.playlist_id == playlist_id)\
        .order_by(PlaylistVideo.position)\
        .all()
        
    return jsonify({
        "playlist": {
            "id": playlist.id,
            "name": playlist.name,
            "description": playlist.description,
            "videos": [{
                "id": video.id,
                "title": video.nickname or os.path.basename(video.original_filepath),
                "thumbnail": video.thumbnail_path,
                "position": pv.position,
                "description": video.description,
                "tags": video.tags,
                "view_count": video.view_count,
                "likes": video.likes
            } for video, pv in videos]
        }
    })

@app.route('/get_playlists')
def playlists():
    playlists = Playlist.query.order_by(desc(Playlist.created_at)).all()
    
    # Get video count and first thumbnail for each playlist
    playlist_info = []
    for playlist in playlists:
        # Convert Playlist object to dict with only the needed attributes
        playlist_dict = {
            'id': playlist.id,
            'name': playlist.name,
            'description': playlist.description,
            'created_at': playlist.created_at
        }
        
        video_count = PlaylistVideo.query.filter_by(playlist_id=playlist.id).count()
        
        # Get first video's thumbnail
        first_video = db.session.query(Video)\
            .join(PlaylistVideo)\
            .filter(PlaylistVideo.playlist_id == playlist.id)\
            .order_by(PlaylistVideo.position)\
            .first()
            
        thumbnail = first_video.thumbnail_path if first_video else None
        
        playlist_info.append({
            'playlist': playlist_dict,
            'video_count': video_count,
            'thumbnail': thumbnail
        })
    
    return render_template('playlists.html', playlists=playlist_info)

@app.route('/playlist/<int:playlist_id>')
def playlist_detail(playlist_id):
    playlist = Playlist.query.get_or_404(playlist_id)
    
    # Get all videos in the playlist with their order
    playlist_videos = db.session.query(Video)\
        .join(PlaylistVideo)\
        .filter(PlaylistVideo.playlist_id == playlist_id)\
        .order_by(PlaylistVideo.position)\
        .all()
    
    # Create a JSON-serializable version of the playlist videos
    serialized_videos = [{
        'id': video.id,
        'nickname': video.nickname,
        'original_filepath': video.original_filepath,
        'thumbnail_path': video.thumbnail_path,
        'view_count': video.view_count or 0,
        'likes': video.likes or 0,
        'tags': video.tags
    } for video in playlist_videos]
    
    return render_template('playlist_detail.html', 
                         playlist=playlist, 
                         playlist_videos=playlist_videos,
                         serialized_videos=serialized_videos)

@app.route('/remove_from_playlist/<int:playlist_id>/<int:video_id>', methods=['POST'])
def remove_from_playlist(playlist_id, video_id):
    try:
        playlist_video = PlaylistVideo.query.filter_by(
            playlist_id=playlist_id,
            video_id=video_id
        ).first()
        
        if playlist_video:
            # Get the position of the removed video
            removed_position = playlist_video.position
            
            # Delete the playlist video entry
            db.session.delete(playlist_video)
            
            # Update positions of remaining videos
            PlaylistVideo.query.filter(
                PlaylistVideo.playlist_id == playlist_id,
                PlaylistVideo.position > removed_position
            ).update(
                {PlaylistVideo.position: PlaylistVideo.position - 1}
            )
            
            db.session.commit()
            return jsonify({"success": True}), 200
        else:
            return jsonify({"error": "Video not found in playlist"}), 404
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run("0.0.0.0", 5015, debug=True)
