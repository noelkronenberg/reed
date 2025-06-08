import os
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, Response, session
from pyzotero import zotero
import requests
import json
import logging
from feedgen.feed import FeedGenerator
import random
import time
import base64

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)

API_CALL_DELAY = 1.5 # seconds between API calls
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin')

def verify_admin(username: str, password: str) -> bool:
    """
    Verify admin credentials.
    
    Args:
        username (str): The username to verify
        password (str): The password to verify
        
    Returns:
        bool: True if credentials are valid, False otherwise
    """

    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def rate_limit():
    """
    Add a delay between API calls to prevent overloading.
    """

    logger.debug(f"Rate limiting for {API_CALL_DELAY} seconds")
    time.sleep(API_CALL_DELAY)

def load_api_keys() -> dict:
    """
    Load API keys from environment variables (if admin) or session.
    For admin users, Semantic Scholar API key is loaded from environment.

    Returns:
        dict: A dictionary containing the API keys.
    """
    
    # if admin, try to get Semantic Scholar API key from environment variables
    auth = request.authorization
    if auth and verify_admin(auth.username, auth.password):
        semantic_scholar_api_key = os.getenv('SEMANTIC_SCHOLAR_API_KEY', '')
        if semantic_scholar_api_key:
            logger.debug("Using Semantic Scholar API key from environment variables (admin mode)")
            
            # get other keys from session
            session_keys = session.get('api_keys', {})
            return {
                'zotero_api_key': session_keys.get('zotero_api_key', ''),
                'zotero_user_id': session_keys.get('zotero_user_id', ''),
                'semantic_scholar_api_key': semantic_scholar_api_key
            }
    
    # otherwise, try to get all keys from session
    session_keys = session.get('api_keys', {})
    if session_keys:
        logger.debug(f"Loaded API keys from session (non-admin mode)")
        return session_keys
    
    logger.debug("No API keys found in session")
    return {'zotero_api_key': '', 'zotero_user_id': '', 'semantic_scholar_api_key': ''}

def save_api_keys(keys: dict) -> None:
    """
    Save API keys to session.

    Args:
        keys (dict): A dictionary containing the API keys.
    """
    
    session['api_keys'] = keys
    logger.debug(f"Saved API keys to session")

def fetch_recent_papers(n_papers: int = 100) -> list:
    """
    Fetch the last n_papers from Zotero.

    Args:
        n_papers (int): Number of papers to fetch.

    Returns:
        list: A list of dictionaries containing the recent papers.
    """

    keys = load_api_keys()
    
    if not keys['zotero_api_key'] or not keys['zotero_user_id']:
        logger.debug("Missing Zotero API keys")
        return []
    
    try:
        zotero_client = zotero.Zotero(keys['zotero_user_id'], 'user', keys['zotero_api_key'])
        rate_limit() # add delay before API call
        items = zotero_client.items(limit=n_papers, sort='dateAdded', direction='desc')
        logger.debug(f"Fetched {len(items)} items from Zotero")
        
        # format the papers
        papers = []
        for item in items:
            # only include papers with DOIs
            if item['data'].get('DOI'):

                date = item['data'].get('date', '')
                if date:
                    # parse and format the date
                    try:
                        date_obj = datetime.strptime(date, '%Y-%m-%d')
                        date = date_obj.strftime('%B %d, %Y')
                        logger.debug(f"Formatted date")
                    # keep original date format if parsing fails
                    except:
                        logger.debug(f"Could not parse date: {date}")
                        pass

                paper = {
                    'title': item['data'].get('title', ''),
                    'authors': [creator.get('name', '') for creator in item['data'].get('creators', [])],
                    'doi': item['data'].get('DOI', ''),
                    'abstract': item['data'].get('abstractNote', ''),
                    'date': date,
                    'url': item['data'].get('url', ''),
                    'zotero_url': f"https://www.zotero.org/groups/{keys['zotero_user_id']}/items/{item['key']}"
                }
                papers.append(paper)

        logger.debug(f"Processed {len(papers)} papers with DOIs")
        return papers
    
    except Exception as e:
        logger.error(f"Error fetching papers from Zotero: {str(e)}")
        return []

def get_random_seed_papers(papers: list, n_seed_papers: int = 10) -> list:
    """
    Randomly select n_seed_papers from the list of papers to use as seed for recommendations.

    Args:
        papers (list): List of all papers to choose from.
        n_seed_papers (int): Number of seed papers to select.

    Returns:
        list: A list of n_seed_papers randomly selected papers.
    """

    # if less than n_seed_papers, return all papers
    if len(papers) <= n_seed_papers:
        return papers
    
    # set a fixed seed based on the current date
    today = datetime.now().date()
    random.seed(today.toordinal())

    seed_papers = random.sample(papers, n_seed_papers)
    random.seed()
    
    return seed_papers

def get_paper_recommendations(seed_papers: list, n_recommendations: int = 3) -> list:
    """
    Get paper recommendations from Semantic Scholar based on random seed papers.
    Ensures we get exactly n_recommendations with all required fields.

    Args:
        seed_papers (list): List of papers to use as seed for recommendations.
        n_recommendations (int): Number of recommendations to get.

    Returns:
        list: A list of n_recommendations dictionaries containing the recommendations.
    """

    keys = load_api_keys()
    if not keys['semantic_scholar_api_key'] or not seed_papers:
        logger.debug("Missing Semantic Scholar API key or no seed papers")
        return []
    
    try:
        # prepare paper ids for recommendation
        paper_ids = []
        for paper in seed_papers:
            if paper.get('doi'):
                paper_ids.append(paper['doi'])
                logger.debug("Added DOI for recommendation")
            else:
                logger.debug(f"Paper has no DOI: {paper['title']}")
        
        if not paper_ids:
            logger.debug("No DOIs found in seed papers")
            return []
        
        # attempt to get n_recommendations with all fields
        max_attempts = 5 
        complete_recommendations = []
        
        for attempt in range(max_attempts):
            if len(complete_recommendations) >= n_recommendations:
                break
                
            # call Semantic Scholar Recommendations API with all seed papers as positive examples
            url = "https://api.semanticscholar.org/recommendations/v1/papers"
            headers = {
                'x-api-key': keys['semantic_scholar_api_key'],
                'Content-Type': 'application/json'
            }
            payload = {
                'positivePaperIds': paper_ids
            }
            
            logger.debug(f"Getting recommendations for {len(paper_ids)} papers (attempt {attempt + 1})")
            rate_limit() # add delay before API call
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                params={
                    'fields': 'title,authors,url,publicationDate,abstract',
                    'limit': n_recommendations * 3 # request more papers as buffer
                }
            )
            
            if response.status_code == 200:
                recommendations = response.json().get('recommendedPapers', [])
                logger.debug(f"Received {len(recommendations)} recommendations from Semantic Scholar")
                
                # format and validate the recommendations
                for paper in recommendations:
                    
                    # stop if we have enough recommendations
                    if len(complete_recommendations) >= n_recommendations:
                        break
                        
                    # check if all required fields are present and non-empty
                    if not all([
                        paper.get('title'),
                        paper.get('authors'),
                        paper.get('publicationDate'),
                        paper.get('abstract')
                    ]):
                        logger.debug("Skipping incomplete recommendation")
                        continue

                    # format the date
                    date = paper.get('publicationDate', '')
                    try:
                        date_obj = datetime.strptime(date, '%Y-%m-%d')
                        date = date_obj.strftime('%B %d, %Y')
                        logger.debug("Formatted recommendation date")
                    except:
                        logger.debug(f"Could not parse recommendation date: {date}")
                        continue
                    
                    # format the recommendation
                    formatted_paper = {
                        'title': paper.get('title', ''),
                        'authors': [author.get('name', '') for author in paper.get('authors', [])],
                        'url': paper.get('url', ''),
                        'date': date,
                        'abstract': paper.get('abstract', '')
                    }
                    complete_recommendations.append(formatted_paper)
                    logger.debug("Added complete recommendation")
            
            # if error, log and return on last attempt
            else:
                logger.error(f"Semantic Scholar API error: {response.status_code} - {response.text}")
                if attempt == max_attempts - 1:
                    return complete_recommendations

        logger.debug(f"Final complete recommendations count: {len(complete_recommendations)} (will return first {n_recommendations})")
        return complete_recommendations[:n_recommendations]
        
    except Exception as e:
        logger.error(f"Error getting recommendations: {str(e)}")
        return []

def should_update_recommendations() -> bool:
    """
    Check if recommendations should be updated based on last refresh date in session.
    
    Returns:
        bool: True if recommendations should be updated, False otherwise.
    """
    last_refresh = session.get('last_refresh')
    if not last_refresh:
        logger.debug("No last refresh date found in session")
        return True
        
    # check if last refresh date is before today
    try:
        last_refresh_date = datetime.strptime(last_refresh, '%Y-%m-%d').date()
        logger.debug(f"Last refresh date: {last_refresh_date}")
        return last_refresh_date < datetime.now().date()
    
    except Exception as e:
        logger.error(f"Error checking last refresh date: {str(e)}")
        return True

def update_recommendations(n_seed_papers: int = 10, n_recommendations: int = 3) -> tuple[list, list, str]:
    """
    Update recommendations if needed.

    Args:
        n_seed_papers (int): Number of seed papers to select.
        n_recommendations (int): Number of recommendations to get.
    
    Returns:
        tuple[list, list, str]: A tuple containing (seed_papers, recommendations, last_update_date)
    """
    
    all_papers = fetch_recent_papers(n_papers=n_seed_papers*10)
    seed_papers = []
    recommendations = []
    last_update_date = None
    
    # update recommendations, if needed
    if should_update_recommendations():
        logger.debug("Updating recommendations")
        seed_papers = get_random_seed_papers(all_papers, n_seed_papers=n_seed_papers)
        recommendations = get_paper_recommendations(seed_papers, n_recommendations=n_recommendations)
        
        try:
            current_date = datetime.now().date().strftime('%Y-%m-%d')
            
            # save to session
            session['last_refresh'] = current_date
            session['seed_papers'] = seed_papers
            session['recommendations'] = recommendations
            logger.debug(f"Saved {len(seed_papers)} seed papers and {len(recommendations)} recommendations to session")
            
            last_update_date = current_date
        
        except Exception as e:
            logger.error(f"Error saving data to session: {str(e)}")
    
    # load existing recommendations from session, if available
    else:
        logger.debug("Recommendations are up to date, loading from session")

        seed_papers = session.get('seed_papers', [])
        recommendations = session.get('recommendations', [])
        last_update_date = session.get('last_refresh')
        logger.debug(f"Loaded {len(seed_papers)} seed papers and {len(recommendations)} recommendations from session")
        
        # if session data is empty, generate new recommendations
        if not seed_papers or not recommendations:
            logger.debug("Session data is empty, generating new recommendations")
            seed_papers = get_random_seed_papers(all_papers, n_seed_papers=n_seed_papers)
            recommendations = get_paper_recommendations(seed_papers, n_recommendations=n_recommendations)
            
            try:
                current_date = datetime.now().date().strftime('%Y-%m-%d')

                # save to session
                session['last_refresh'] = current_date
                session['seed_papers'] = seed_papers
                session['recommendations'] = recommendations
                logger.debug(f"Saved {len(seed_papers)} seed papers and {len(recommendations)} recommendations to session")

                last_update_date = current_date
                
            except Exception as e:
                logger.error(f"Error saving data to session: {str(e)}")
    
    # ensure we have valid data before returning
    if not seed_papers or not recommendations:
        logger.warning("No seed papers or recommendations available")
        return [], [], last_update_date
        
    return seed_papers, recommendations, last_update_date

@app.route('/login')
def login() -> str:
    """
    Handle admin login.

    Returns:
        str: Redirect to index page or trigger Basic Auth.
    """
    
    # check for Basic Auth credentials
    auth = request.authorization
    if auth and verify_admin(auth.username, auth.password):
        flash('Successfully logged in!')
        return redirect(url_for('index'))

    # trigger browser's Basic Auth dialog
    return Response(
        'Please authenticate',
        401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

@app.route('/logout')
def logout() -> str:
    """
    Handle admin logout.

    Returns:
        str: Redirect to index page.
    """

    response = redirect(url_for('index'))
    response.headers['Clear-Site-Data'] = '"cache", "cookies", "storage"'
    return response

@app.route('/')
def index() -> str:
    """
    Render the main page.

    Returns:
        str: The rendered main page.
    """

    keys = load_api_keys()
    seed_papers, recommendations, last_update_date = update_recommendations(n_seed_papers=10, n_recommendations=3)
    logger.debug(f"Rendering index with {len(seed_papers)} seed papers and {len(recommendations)} recommendations")
    
    auth = request.authorization
    is_admin = auth and verify_admin(auth.username, auth.password)
    
    return render_template('index.html', 
                         seed_papers=seed_papers,
                         recommendations=recommendations,
                         has_keys=all(keys.values()),
                         last_update_date=last_update_date,
                         keys=keys,
                         is_admin=is_admin)

@app.route('/api/keys', methods=['GET', 'POST'])
def manage_keys() -> str:
    """
    Manage API keys.

    Returns:
        str: The rendered keys page.
    """

    if request.method == 'POST':
        # if admin, preserve Semantic Scholar API key from environment
        auth = request.authorization
        if auth and verify_admin(auth.username, auth.password):
            semantic_scholar_api_key = os.getenv('SEMANTIC_SCHOLAR_API_KEY', '')
            logger.debug("Using Semantic Scholar API key from environment variables (admin mode)")
        else:
            semantic_scholar_api_key = request.form.get('semantic_scholar_api_key', '')
            logger.debug("Using Semantic Scholar API key from form (non-admin mode)")

        keys = {
            'zotero_api_key': request.form.get('zotero_api_key', ''),
            'zotero_user_id': request.form.get('zotero_user_id', ''),
            'semantic_scholar_api_key': semantic_scholar_api_key
        }
        save_api_keys(keys)
        flash('API keys saved successfully!')
        return redirect(url_for('index'))
    
    keys = load_api_keys()
    return render_template('keys.html', keys=keys)

@app.route('/api/papers')
def get_papers() -> json:
    """
    API endpoint to get seed papers.

    Returns:
        json: A JSON object containing the seed papers.
    """

    seed_papers, _, _ = update_recommendations()
    logger.debug(f"API /papers returning {len(seed_papers)} papers")
    return jsonify(seed_papers)

@app.route('/api/recommendations')
def get_recommendations() -> json:
    """
    API endpoint to get recommendations.

    Returns:
        json: A JSON object containing the recommendations.
    """
    
    _, recommendations, _ = update_recommendations()
    logger.debug(f"API /recommendations returning {len(recommendations)} recommendations")
    return jsonify(recommendations)

@app.route('/feed.xml')
def rss_feed() -> Response:
    """
    Generate RSS feed of paper recommendations (disabled for now).

    Returns:
        Response: 503 Service Unavailable response.
    """

    if False: # disable RSS feed for now
        _, recommendations, last_update_date = update_recommendations(n_seed_papers=10, n_recommendations=3)
        
        fg = FeedGenerator()
        fg.title('Paper Recommendations')
        fg.description('Latest paper recommendations based on your Zotero library')
        fg.link(href=request.url_root)
        fg.language('en')
        
        if last_update_date:
            # add timezone info to the datetime
            date_obj = datetime.strptime(last_update_date, '%Y-%m-%d')
            date_obj = date_obj.replace(tzinfo=timezone.utc)
            fg.updated(date_obj)
        
        for paper in recommendations:
            fe = fg.add_entry()
            fe.title(paper['title'])
            fe.link(href=paper['url'])
            fe.description(paper['abstract'])
            fe.author(name=', '.join(paper['authors']))
            if paper['date']:
                try:
                    # add timezone info to the publication date
                    pub_date = datetime.strptime(paper['date'], '%B %d, %Y')
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                    fe.published(pub_date)
                except:
                    pass
        
        return Response(fg.rss_str(pretty=True), mimetype='application/rss+xml')
    else:
        return Response('RSS feed is currently not available', status=503)