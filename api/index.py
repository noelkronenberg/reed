from flask import Flask, render_template, jsonify, request
import arxiv
import logging
from datetime import datetime
from typing import List, Dict, Any
import time

# configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

CACHE_DURATION = 86400 # cache papers for 1 day (in seconds)
paper_cache = {}

def build_search_query(keywords: str = '') -> str:
    """
    Build arXiv search query combining ML categories with keywords.
    
    Args:
        keywords (str): Comma-separated keywords to search for.
    
    Returns:
        str: Combined arXiv search query.
    """

    # base query for ml categories
    base_query = "(cat:cs.LG OR cat:cs.AI OR cat:stat.ML)"
    
    if not keywords:
        logger.info("No keywords provided, using base ml categories query")
        return base_query
    
    # process keywords
    keyword_list = [k.strip() for k in keywords.split(',') if k.strip()]
    if not keyword_list:
        logger.info("No valid keywords after processing, using base ml categories query")
        return base_query
    
    # build keyword query - search in title and abstract
    keyword_queries = []
    for keyword in keyword_list:
        # search for exact phrase in title or abstract
        keyword_queries.append(f'(ti:"{keyword}" OR abs:"{keyword}")')
    
    keyword_query = " AND ".join(keyword_queries)
    final_query = f"{base_query} AND ({keyword_query})"
    
    logger.info(f"Built query: {final_query}")
    
    return final_query

def fetch_recent_papers(max_results: int = 100, keywords: str = '') -> List[Dict[str, Any]]:
    """
    Fetch recent ML papers from arXiv with caching.
    
    Args:
        max_results (int): Maximum number of papers to fetch.
        keywords (str): Comma-separated keywords to search for.
    
    Returns:
        List[Dict[str, Any]]: List of paper dictionaries.
    """

    current_time = time.time()
    search_query = build_search_query(keywords)
    
    # check cache for this specific query
    if search_query in paper_cache:
        cache_time, cached_papers = paper_cache[search_query]
        if current_time - cache_time < CACHE_DURATION:
            logger.info(f"Using cached papers for query '{search_query}' (age: {int(current_time - cache_time)}s)")
            return cached_papers
        else:
            logger.info(f"Cache expired for query '{search_query}'")
    
    try:
        logger.info(f"Fetching {max_results} papers from arxiv with query: {search_query}")
        
        # search for recent papers
        search = arxiv.Search(
            query=search_query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )
        
        # create a client and get results
        client = arxiv.Client()
        papers = []
        for i, result in enumerate(client.results(search), 1):
            time.sleep(0.1) # buffer between requests
            if i % 10 == 0:
                logger.info(f"Processed {i} papers...")
            
            papers.append({
                'title': result.title,
                'authors': [author.name for author in result.authors],
                'abstract': result.summary,
                'pdf_url': result.pdf_url,
                'published': result.published.strftime('%Y-%m-%d'),
                'id': result.entry_id,
                'categories': result.categories
            })
        
        # update cache for this query
        paper_cache[search_query] = (current_time, papers)
        logger.info(f"Successfully fetched and cached {len(papers)} papers for query '{search_query}'")
        
        return papers
        
    except Exception as e:
        logger.error(f"Error fetching papers: {str(e)}", exc_info=True)
        
        # return cached papers even if expired in case of error
        if search_query in paper_cache:
            _, cached_papers = paper_cache[search_query]
            logger.info(f"Falling back to expired cache with {len(cached_papers)} papers")
            return cached_papers
        
        logger.error("No cached papers available for fallback")
        return []

@app.route('/')
def index():
    """Render the main page."""
    logger.info("Serving index page")
    cache_hours = CACHE_DURATION // 3600
    return render_template('index.html', cache_hours=cache_hours)

@app.route('/api/papers')
def get_papers():
    """
    Get recent ML papers.
    
    Query Parameters:
        keywords (str): Optional comma-separated keywords to search for.
    
    Returns:
        JSON response containing:
            - papers (List[Dict]): List of recent papers
            - timestamp (str): When the papers were fetched
            - cache_status (str): Whether the response is from cache
            - total_searched (int): Total number of papers searched
            - match_percentage (float): Percentage of papers that matched
    """

    try:
        keywords = request.args.get('keywords', '')
        logger.info(f"Received request for papers with keywords: {keywords}")
        
        papers = fetch_recent_papers(keywords=keywords)
        current_time = time.time()
        search_query = build_search_query(keywords)
        
        # determine if response is from cache
        cache_status = "fresh"
        if search_query not in paper_cache:
            cache_status = "initial"
            logger.info("No cache available - initial fetch")
        else:
            cache_time, _ = paper_cache[search_query]
            if current_time - cache_time >= CACHE_DURATION:
                cache_status = "expired"
                logger.info(f"Cache expired (age: {int(current_time - cache_time)}s)")
            else:
                logger.info(f"Using fresh cache (age: {int(current_time - cache_time)}s)")
        
        # calculate match statistics
        total_searched = 100  # we always search max_results=100
        match_percentage = (len(papers) / total_searched) * 100 if total_searched > 0 else 0
        
        response = {
            'papers': papers,
            'timestamp': datetime.now().isoformat(),
            'cache_status': cache_status,
            'cache_age': current_time - cache_time if search_query in paper_cache else None,
            'total_searched': total_searched,
            'match_percentage': round(match_percentage, 1),
            'search_query': search_query
        }
        logger.info(f"Returning {len(papers)} papers with status: {cache_status} ({match_percentage:.1f}% match)")
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error in get_papers: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("Starting paper feed application")
    app.run(debug=True)