document.addEventListener('DOMContentLoaded', () => {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const uploadContainer = document.getElementById('upload-progress-container');
    const uploadFill = document.getElementById('upload-progress-fill');
    const uploadStatus = document.getElementById('upload-status');
    const jobsContainer = document.getElementById('jobs-container');
    const jobCardTemplate = document.getElementById('job-card-template');

    let activeUpload = false;
    let pollInterval = null;

    // Load initial jobs
    fetchJobs();
    startPolling();

    // Drag and drop event listeners
    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        
        if (activeUpload) {
            alert('An upload is already in progress in this tab.');
            return;
        }

        if (e.dataTransfer.files.length) {
            handleFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (activeUpload) {
            alert('An upload is already in progress in this tab.');
            return;
        }
        
        if (e.target.files.length) {
            handleFile(e.target.files[0]);
        }
    });

    function handleFile(file) {
        if (!file.name.toLowerCase().endsWith('.mp3') && !file.type.includes('audio')) {
            alert('Please select an .mp3 file.');
            return;
        }

        uploadFile(file);
    }

    function uploadFile(file) {
        activeUpload = true;
        uploadContainer.style.display = 'block';
        uploadStatus.textContent = 'Uploading...';
        uploadFill.style.width = '0%';
        dropzone.querySelector('.dropzone-content').style.display = 'none';

        const xhr = new XMLHttpRequest();
        const formData = new FormData();
        formData.append('file', file);

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 100;
                uploadFill.style.width = percentComplete + '%';
            }
        });

        xhr.addEventListener('load', () => {
            activeUpload = false;
            if (xhr.status >= 200 && xhr.status < 300) {
                uploadStatus.textContent = 'Upload complete! Processing...';
                fetchJobs(); // immediately fetch to see new job
            } else {
                uploadStatus.textContent = 'Upload failed: ' + (xhr.responseText || 'Server error');
                uploadFill.style.background = '#e57373';
            }
            resetDropzoneAfterDelay();
        });

        xhr.addEventListener('error', () => {
            activeUpload = false;
            uploadStatus.textContent = 'Upload failed: Network error';
            uploadFill.style.background = '#e57373';
            resetDropzoneAfterDelay();
        });

        xhr.open('POST', '/api/v1/eridian-echo/upload');
        xhr.send(formData);
    }

    function resetDropzoneAfterDelay() {
        setTimeout(() => {
            if (!activeUpload) {
                uploadContainer.style.display = 'none';
                uploadFill.style.background = 'linear-gradient(90deg, #4caf50, #8bc34a)';
                dropzone.querySelector('.dropzone-content').style.display = 'block';
                fileInput.value = '';
            }
        }, 3000);
    }

    function fetchJobs() {
        fetch('/api/v1/eridian-echo/jobs')
            .then(res => res.json())
            .then(jobs => {
                renderJobs(jobs);
            })
            .catch(err => console.error('Failed to fetch jobs:', err));
    }

    function renderJobs(jobs) {
        jobsContainer.innerHTML = '';
        if (!jobs || jobs.length === 0) return;

        jobs.forEach(job => {
            const clone = jobCardTemplate.content.cloneNode(true);
            const card = clone.querySelector('.job-card');
            
            const title = clone.querySelector('.filename');
            title.textContent = job.filename;
            
            const timestamp = clone.querySelector('.job-timestamp');
            if (job.created_at) {
                const d = new Date(job.created_at);
                timestamp.textContent = "Uploaded on " + d.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
            }
            
            const badge = clone.querySelector('.status-badge');
            badge.textContent = job.status;
            badge.classList.add('status-' + job.status);

            const content = clone.querySelector('.transcript-content');
            const copyBtn = clone.querySelector('.copy-btn');
            const deleteBtn = clone.querySelector('.delete-btn');

            if (job.status === 'succeeded' && job.transcript) {
                content.textContent = job.transcript;
                copyBtn.style.display = 'inline-block';
                copyBtn.addEventListener('click', () => {
                    navigator.clipboard.writeText(job.transcript).then(() => {
                        const origText = copyBtn.textContent;
                        copyBtn.textContent = 'Copied!';
                        setTimeout(() => copyBtn.textContent = origText, 2000);
                    });
                });
            } else if (job.status === 'failed' && job.error) {
                content.textContent = 'Error: ' + job.error;
                content.classList.add('error-text');
            } else if (job.status === 'processing' || job.status === 'queued') {
                content.textContent = 'Waiting for LLM transcription...';
                content.style.fontStyle = 'italic';
                content.style.color = '#666';
            }

            deleteBtn.addEventListener('click', () => {
                if (confirm('Are you sure you want to delete this recording and transcript?')) {
                    fetch('/api/v1/eridian-echo/jobs/' + job.id, { method: 'DELETE' })
                        .then(res => {
                            if (res.ok) fetchJobs();
                            else alert('Failed to delete job.');
                        })
                        .catch(err => alert('Failed to delete job: ' + err));
                }
            });

            jobsContainer.appendChild(clone);
        });
    }

    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(() => {
            fetchJobs();
        }, 5000);
    }
    
    // Support Ctrl-A / Cmd-A selection inside transcript boxes
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
            const activeEl = document.activeElement;
            if (activeEl && activeEl.classList.contains('transcript-content')) {
                e.preventDefault();
                const range = document.createRange();
                range.selectNodeContents(activeEl);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            }
        }
    });
});
