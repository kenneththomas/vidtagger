const tagInput = document.getElementById('tag-input');
const tagContainer = document.getElementById('tag-input-container');
const tagSuggestions = document.getElementById('tag-suggestions');
let tags = [];
let videoId;

function initializeTags() {
    videoId = tagContainer.dataset.videoId;
    const initialTags = tagContainer.dataset.tags.split(',').filter(tag => tag.trim() !== '');
    tags = initialTags;
    updateTagDisplay();
}

function updateTagDisplay() {
    tagContainer.innerHTML = '';
    tags.forEach(tag => {
        if (tag.trim() !== '') {
            const tagPill = document.createElement('span');
            tagPill.className = 'tag-pill';
            tagPill.innerHTML = `${tag.trim()}<button type="button" onclick="removeTag('${tag.trim()}')">&times;</button>`;
            tagContainer.appendChild(tagPill);
        }
    });
}

function addTag(tag) {
    if (tag && !tags.includes(tag)) {
        tags.push(tag);
        updateTagDisplay();
        updateTagsOnServer();
        tagInput.value = '';
    }
}

function removeTag(tag) {
    tags = tags.filter(t => t !== tag);
    updateTagDisplay();
    updateTagsOnServer();
}

function updateTagsOnServer() {
    const newTags = tags.join(',');
    fetch(`/edit_tags/${videoId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: `tags=${encodeURIComponent(newTags)}`
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            console.error('Error updating tags:', data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
    });
}

tagInput.addEventListener('input', function() {
    const input = this.value.toLowerCase();
    if (input) {
        fetch(`/get_tag_suggestions?q=${input}`)
            .then(response => response.json())
            .then(data => {
                tagSuggestions.innerHTML = '';
                data.forEach(tag => {
                    const div = document.createElement('div');
                    div.textContent = tag;
                    div.onclick = function() {
                        addTag(tag);
                        tagSuggestions.style.display = 'none';
                    };
                    tagSuggestions.appendChild(div);
                });
                tagSuggestions.style.display = 'block';
            });
    } else {
        tagSuggestions.style.display = 'none';
    }
});

tagInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        addTag(this.value.trim());
    }
});

document.addEventListener('click', function(e) {
    if (e.target !== tagInput && e.target !== tagSuggestions) {
        tagSuggestions.style.display = 'none';
    }
});

function toggleDescriptionEdit() {
    const displayElem = document.getElementById('description-display');
    const editElem = document.getElementById('description-edit');
    const editBtn = document.getElementById('edit-description-btn');
    const saveBtn = document.getElementById('save-description-btn');

    if (displayElem.style.display !== 'none') {
        displayElem.style.display = 'none';
        editElem.style.display = 'block';
        editBtn.style.display = 'none';
        saveBtn.style.display = 'inline-block';
    } else {
        displayElem.style.display = 'block';
        editElem.style.display = 'none';
        editBtn.style.display = 'inline-block';
        saveBtn.style.display = 'none';
    }
}

function editDescription(videoId) {
    const newDescription = document.getElementById('description-edit').value;
    fetch(`/edit_description/${videoId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: `description=${encodeURIComponent(newDescription)}`
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            document.getElementById('description-display').textContent = newDescription;
            toggleDescriptionEdit();
            alert('Description updated successfully!');
        } else {
            alert('Error updating description: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An unexpected error occurred. Please try again.');
    });
}

document.addEventListener('DOMContentLoaded', initializeTags);

// Update the displayTags function to make tags clickable
function displayTags(container, tags) {
    container.innerHTML = '';
    if (tags) {
        tags.split(',').forEach(tag => {
            if (tag.trim()) {
                const tagLink = document.createElement('a');
                tagLink.href = `/filter?tag=${encodeURIComponent(tag.trim())}`;
                tagLink.className = 'tag';
                tagLink.textContent = tag.trim();
                container.appendChild(tagLink);
            }
        });
    }
}

function likeVideo(videoId) {
    fetch(`/like/${videoId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            document.querySelector('.like-count').textContent = `${data.new_like_count} likes`;
            const likeBtn = document.getElementById('like-btn');
            likeBtn.classList.add('liked');
        }
    })
    .catch(error => console.error('Error:', error));
}

async function submitComment(videoId) {
    const author = document.getElementById('comment-author').value.trim();
    const content = document.getElementById('comment-content').value.trim();
    
    if (!author || !content) {
        alert('Please enter both your name and a comment');
        return;
    }
    
    try {
        const response = await fetch(`/add_comment/${videoId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `author=${encodeURIComponent(author)}&content=${encodeURIComponent(content)}`
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Create new comment element
            const commentsList = document.querySelector('.comments-list');
            const newComment = document.createElement('div');
            newComment.className = 'comment';
            newComment.innerHTML = `
                <div class="comment-header">
                    <strong class="comment-author">${data.comment.author}</strong>
                    <span class="comment-timestamp">${data.comment.timestamp}</span>
                </div>
                <div class="comment-content">${data.comment.content}</div>
                <div class="comment-footer">
                    <button class="like-comment-btn" onclick="likeComment(${data.comment.id})">
                        👍 <span class="comment-like-count" data-comment-id="${data.comment.id}">0</span>
                    </button>
                </div>
            `;
            
            // Add to top of comments list
            commentsList.insertBefore(newComment, commentsList.firstChild);
            
            // Clear form
            document.getElementById('comment-author').value = '';
            document.getElementById('comment-content').value = '';
        } else {
            alert('Error posting comment');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error posting comment');
    }
}

async function likeComment(commentId) {
    try {
        const response = await fetch(`/like_comment/${commentId}`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            // Update the like count display
            const likeCountElement = document.querySelector(`.comment-like-count[data-comment-id="${commentId}"]`);
            if (likeCountElement) {
                likeCountElement.textContent = data.new_like_count;
            }
        }
    } catch (error) {
        console.error('Error:', error);
    }
}
