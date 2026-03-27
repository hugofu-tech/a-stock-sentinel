"""
Post Deduplication & State Management
Tracks seen posts to avoid duplicate processing.
Uses a JSON file for persistence across runs.
"""

import json
import os
import time
import logging
from trump_config import POST_STORE_FILE, MAX_STORED_POSTS

logger = logging.getLogger(__name__)


class PostStore:
    """Manages seen post IDs and metadata for deduplication."""

    def __init__(self, store_file=None):
        self.store_file = store_file or POST_STORE_FILE
        self.posts = {}
        self._load()

    def _load(self):
        """Load stored posts from disk."""
        if os.path.exists(self.store_file):
            try:
                with open(self.store_file, 'r', encoding='utf-8') as f:
                    self.posts = json.load(f)
                logger.info(f"Loaded {len(self.posts)} stored posts")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load post store: {e}")
                self.posts = {}
        else:
            self.posts = {}

    def _save(self):
        """Persist posts to disk."""
        os.makedirs(os.path.dirname(self.store_file) or '.', exist_ok=True)
        # Prune old entries if exceeding max
        if len(self.posts) > MAX_STORED_POSTS:
            sorted_posts = sorted(self.posts.items(), key=lambda x: x[1].get('seen_at', 0))
            self.posts = dict(sorted_posts[-MAX_STORED_POSTS:])

        with open(self.store_file, 'w', encoding='utf-8') as f:
            json.dump(self.posts, f, ensure_ascii=False, indent=2)

    def is_seen(self, post_id):
        """Check if a post has already been processed."""
        return str(post_id) in self.posts

    def mark_seen(self, post_id, metadata=None):
        """Mark a post as seen with optional metadata."""
        self.posts[str(post_id)] = {
            'seen_at': time.time(),
            **(metadata or {})
        }
        self._save()

    def get_new_posts(self, posts):
        """Filter a list of posts, returning only unseen ones.

        Args:
            posts: List of dicts, each must have an 'id' key.

        Returns:
            List of unseen posts.
        """
        new_posts = []
        for post in posts:
            post_id = post.get('id')
            if post_id and not self.is_seen(post_id):
                new_posts.append(post)
        return new_posts

    def mark_batch_seen(self, posts):
        """Mark multiple posts as seen."""
        for post in posts:
            post_id = post.get('id')
            if post_id:
                self.posts[str(post_id)] = {
                    'seen_at': time.time(),
                    'source': post.get('source', 'unknown'),
                    'preview': post.get('content', '')[:100]
                }
        self._save()

    def stats(self):
        """Return store statistics."""
        return {
            'total_posts': len(self.posts),
            'store_file': self.store_file
        }
