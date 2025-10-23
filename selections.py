import streamlit as st
import pandas as pd
import numpy as np
from os import path
import os
from datetime import datetime
import requests
import json
import random
import base64
import time
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from io import BytesIO

# Configure Streamlit page
st.set_page_config(
    page_title="Book Club Selections",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Add custom CSS for simple floating elements
st.markdown("""
<style>
    /* Simple fade-in animation for floating elements */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    /* Mobile responsive adjustments */
    @media (max-width: 768px) {
        div[style*="position: fixed"] {
            position: relative !important;
            top: auto !important;
            right: auto !important;
            margin: 10px 0 !important;
            max-width: 100% !important;
        }
    }
</style>
""", unsafe_allow_html=True)

DATA_DIR = 'data_files/'

# Load Hardcover API token
def load_api_token():
    """Load the Hardcover API token from Streamlit secrets or environment variables"""
    try:
        # First try Streamlit secrets (for Streamlit Cloud deployment)
        if hasattr(st, 'secrets') and 'HARDCOVER_API_TOKEN' in st.secrets:
            return st.secrets['HARDCOVER_API_TOKEN']
        
        # Fallback to environment variable (for local development)
        import os
        token = os.getenv('HARDCOVER_API_TOKEN')
        if token:
            return token
            
        # Final fallback to token.txt for local development
        try:
            with open('token.txt', 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            pass
            
        st.error("🔐 Authentication required. Please configure your book database access.")
        st.info("Contact your administrator for setup instructions.")
        return None
        
    except Exception as e:
        st.error(f"Error loading API token: {str(e)}")
        return None

def safe_display_image(image_url, width=150, fallback_text="📚 Cover unavailable"):
    """
    Safely display an image with proper error handling for Streamlit image loading issues
    """
    if not image_url or not isinstance(image_url, str) or not image_url.strip():
        st.write("📚 No cover")
        return
    
    try:
        # Try to display the image
        st.image(image_url, width=width)
    except Exception as e:
        # If image loading fails, show fallback text
        st.write(fallback_text)
        # Optionally log the error for debugging
        # st.caption(f"Debug: {str(e)[:50]}...")

def search_hardcover_api(author=None, title=None, genre=None):
    """
    Search for books based on criteria using field-specific search
    """
    token = load_api_token()
    if not token:
        return None
    
    headers = {
        'Authorization': token,
        'Content-Type': 'application/json'
    }
    
    api_url = "https://api.hardcover.app/v1/graphql"
    
    # Build field-specific search query
    search_parts = []
    
    if author:
        # Target author field specifically
        search_parts.append(f'author:"{author}"')
    
    if title:
        # Target title field specifically
        search_parts.append(f'title:"{title}"')
    
    if genre:
        # Target genre field specifically
        search_parts.append(f'genre:"{genre}"')
    
    # Join with AND logic for field-specific search
    search_query = " AND ".join(search_parts) if search_parts else ""
    
    # If the field-specific approach doesn't work, fall back to books endpoint
    # Let's try the books query with filters first
    query = """
    query SearchBooks($authorFilter: String, $titleFilter: String, $genreFilter: String, $perPage: Int!, $page: Int!) {
        books(
            where: {
                AND: [
                    { author_names: { contains: $authorFilter } }
                    { title: { contains: $titleFilter } }
                    { genres: { contains: $genreFilter } }
                ]
            }
            per_page: $perPage
            page: $page
        ) {
            edges {
                node {
                    id
                    title
                    subtitle
                    author_names
                    genres
                    release_year
                    pages
                    rating
                    ratings_count
                    users_count
                    description
                    series_names
                    featured_series_position
                    has_audiobook
                    has_ebook
                    compilation
                    image {
                        url
                    }
                }
            }
            page_info {
                has_next_page
                has_previous_page
            }
        }
    }
    """
    
    variables = {
        "authorFilter": author,
        "titleFilter": title,
        "genreFilter": genre,
        "perPage": 50,  # Reduced for faster response
        "page": 1
    }
    
    payload = {
        "query": query,
        "variables": variables
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Check if the books query worked
        if 'data' in result and 'books' in result['data'] and result['data']['books']:
            books_data = result['data']['books']['edges']
            
            # Transform to match expected format
            hits = []
            for edge in books_data:
                hits.append({
                    'document': edge['node']
                })
            
            # Create response in expected format
            formatted_response = {
                'data': {
                    'search': {
                        'results': {
                            'hits': hits,
                            'found': len(hits)
                        }
                    }
                }
            }
            return formatted_response
        
        # If books query failed, try simplified fallback search approach
        return _simplified_fallback_search(author, title, genre, headers, api_url)
        
    except requests.exceptions.RequestException as e:
        st.error(f"Search request failed: {str(e)}")
        return None
    except json.JSONDecodeError as e:
        st.error(f"Search response error: {str(e)}")
        return None

def _simplified_fallback_search(author=None, title=None, genre=None, headers=None, api_url=None):
    """
    Fast simplified fallback search - optimized for speed over completeness
    """
    # Strategy: Single search with best query term, limited results
    search_term = None
    
    if author:
        # Use full author name for best match
        search_term = f'"{author}"'
    elif title:
        # Use title search
        search_term = f'"{title}"'
    elif genre:
        # Use genre search
        search_term = genre
    
    if not search_term:
        return None
    
    # Single fast search with limited results
    results = _perform_single_search(search_term, headers, api_url, max_results=75)
    
    if results:
        # Apply client-side filtering for accuracy
        filtered_result = _apply_field_filters(results, author, title, genre)
        return filtered_result
    
    return None

def _fallback_search(author=None, title=None, genre=None, headers=None, api_url=None):
    """
    Fallback search using exhaustive search strategies to ensure comprehensive results
    """
    all_results = []
    
    # Strategy 1: For author searches, try exhaustive approaches
    if author:
        author_queries = []
        author_words = author.split()
        
        if len(author_words) > 1:
            # Try every combination to maximize coverage
            author_queries.append(author_words[-1])  # "Murakami"
            author_queries.append(author_words[0])   # "Haruki"  
            author_queries.append(" ".join(author_words))  # "Haruki Murakami"
            author_queries.append(f'"{author}"')  # "Haruki Murakami"
            
            # Also try partial combinations for maximum coverage
            if len(author_words) == 2:
                author_queries.append(f"{author_words[0]} {author_words[1]}")  # Different spacing
        else:
            author_queries.append(author)
        
        # Try key author queries (reduced for speed)
        for query in author_queries[:3]:  # Limit to first 3 queries for speed
            results = _perform_single_search(query, headers, api_url, max_results=50)
            if results:
                hits = results.get('data', {}).get('search', {}).get('results', {}).get('hits', [])
                all_results.extend(hits)
    
    # Strategy 2: Title search (if provided) - simplified
    if title:
        # Try just the main title query for speed
        results = _perform_single_search(f'"{title}"', headers, api_url, max_results=50)
        if results:
            hits = results.get('data', {}).get('search', {}).get('results', {}).get('hits', [])
            all_results.extend(hits)
    
    # Strategy 3: Genre search (if provided) - simplified  
    if genre:
        results = _perform_single_search(genre, headers, api_url, max_results=50)
        if results:
            hits = results.get('data', {}).get('search', {}).get('results', {}).get('hits', [])
            all_results.extend(hits)
    
    # Remove duplicates based on book ID
    unique_results = {}
    for hit in all_results:
        book_id = hit.get('document', {}).get('id')
        if book_id and book_id not in unique_results:
            unique_results[book_id] = hit
    
    # Create combined response
    if unique_results:
        combined_response = {
            'data': {
                'search': {
                    'results': {
                        'hits': list(unique_results.values()),
                        'found': len(unique_results)
                    }
                }
            }
        }
        
        # Apply client-side filtering
        filtered_result = _apply_field_filters(combined_response, author, title, genre)
        return filtered_result
    
    return None

def _perform_single_search(search_query, headers, api_url, max_results=75):
    """
    Perform a single search query with optimized pagination for speed
    """
    all_hits = []
    page = 1
    max_pages = 3  # Limit to 3 pages for speed (75 results max)
    
    while len(all_hits) < max_results and page <= max_pages:
        query = """
        query SearchBooks($query: String!, $queryType: String!, $perPage: Int!, $page: Int!) {
            search(
                query: $query, 
                query_type: $queryType, 
                per_page: $perPage, 
                page: $page
            ) {
                results
                query
                query_type
                page
                per_page
            }
        }
        """
        
        variables = {
            "query": search_query,
            "queryType": "Book",
            "perPage": 25,  # Use API's natural limit
            "page": page
        }

        payload = {
            "query": query,
            "variables": variables
        }

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=8)
            response.raise_for_status()
            result = response.json()
            
            if result and 'data' in result:
                hits = result.get('data', {}).get('search', {}).get('results', {}).get('hits', [])
                
                if not hits:  # No more results
                    break
                    
                all_hits.extend(hits)
                
                # If we got less than perPage results, we've reached the end
                if len(hits) < 25:
                    break
                    
                page += 1
                
            else:
                break
                
        except:
            break
    
    # Create response in expected format
    if all_hits:
        return {
            'data': {
                'search': {
                    'results': {
                        'hits': all_hits,
                        'found': len(all_hits)
                    }
                }
            }
        }
    
    return None

def _apply_field_filters(api_response, author_filter=None, title_filter=None, genre_filter=None):
    """
    Apply client-side filters to ensure field-specific matching
    """
    if not api_response or 'data' not in api_response:
        return api_response
    
    search_data = api_response.get('data', {}).get('search', {})
    results = search_data.get('results', {})
    hits = results.get('hits', [])
    
    if not hits:
        return api_response
    
    filtered_hits = []
    original_count = len(hits)
    
    for hit in hits:
        book = hit.get('document', {})
        include_book = True
        
        # Filter by author if specified
        if author_filter:
            author_names = book.get('author_names', [])
            author_match = False
            
            # Check for flexible author matching
            author_filter_lower = author_filter.lower()
            author_words = author_filter_lower.split()
            
            for author_name in author_names:
                author_name_lower = author_name.lower()
                
                # Check if all words from search appear in author name
                if all(word in author_name_lower for word in author_words):
                    author_match = True
                    break
                    
                # Also check reverse (in case of different name order)
                if author_filter_lower in author_name_lower:
                    author_match = True
                    break
            
            if not author_match:
                include_book = False
        
        # Filter by title if specified
        if title_filter and include_book:
            book_title = book.get('title', '')
            if title_filter.lower() not in book_title.lower():
                include_book = False
        
        # Filter by genre if specified
        if genre_filter and include_book:
            book_genres = book.get('genres', [])
            # Check if any genre contains the search term (case-insensitive)
            genre_match = any(
                genre_filter.lower() in genre.lower() 
                for genre in book_genres
            )
            if not genre_match:
                include_book = False
        
        if include_book:
            filtered_hits.append(hit)
    
    # Update the results with filtered hits
    search_data['results']['hits'] = filtered_hits
    search_data['results']['found'] = len(filtered_hits)
    
    return api_response

def clean_duplicate_books():
    """
    Remove duplicate books from the CSV file (keeps the first occurrence)
    """
    try:
        df = pd.read_csv(path.join(DATA_DIR, 'book_selections.csv'))
        if not df.empty:
            # Remove duplicates based on 'id' column, keep first occurrence
            original_count = len(df)
            df_cleaned = df.drop_duplicates(subset=['id'], keep='first')
            removed_count = original_count - len(df_cleaned)
            
            if removed_count > 0:
                # Save cleaned data back to CSV
                df_cleaned.to_csv(path.join(DATA_DIR, 'book_selections.csv'), index=False)
                return removed_count
            return 0
    except Exception as e:
        st.error(f"Error cleaning duplicates: {str(e)}")
        return 0

def remove_last_selection():
    """
    Remove the most recent book selection from history
    """
    try:
        history_df = load_selection_history()
        if history_df.empty:
            return False, "No selections to remove"
        
        # Get the last selection info before removing
        last_selection = history_df.sort_values('selection_round', ascending=False).iloc[0]
        last_title = last_selection['title']
        last_round = last_selection['selection_round']
        
        # Remove the last selection (highest round number)
        max_round = history_df['selection_round'].max()
        updated_history = history_df[history_df['selection_round'] != max_round]
        
        # Save updated history back to CSV
        updated_history.to_csv(path.join(DATA_DIR, 'selection_history.csv'), index=False)
        
        return True, f"Removed '{last_title}' from Round {last_round}"
        
    except Exception as e:
        return False, f"Error removing selection: {str(e)}"

def clear_all_selections():
    """
    Clear all book selections from history
    """
    try:
        # Create empty DataFrame with required columns
        columns = ['selection_date', 'book_id', 'title', 'author_names', 'genres', 
                  'release_year', 'pages', 'rating', 'selection_round']
        empty_df = pd.DataFrame(columns=columns)
        
        # Save empty DataFrame to CSV
        empty_df.to_csv(path.join(DATA_DIR, 'selection_history.csv'), index=False)
        
        return True, "All selections cleared"
        
    except Exception as e:
        return False, f"Error clearing selections: {str(e)}"

def load_book_list():
    """
    Load the current book list from CSV file
    """
    try:
        df = pd.read_csv(path.join(DATA_DIR, 'book_selections.csv'))
        return df
    except FileNotFoundError:
        # Create empty DataFrame with required columns if file doesn't exist
        columns = ['id', 'title', 'author_names', 'release_year', 'pages', 'rating', 
                  'ratings_count', 'genres', 'description', 'image_url', 'added_date']
        df = pd.DataFrame(columns=columns)
        return df
    except Exception as e:
        st.error(f"Error loading book list: {str(e)}")
        return pd.DataFrame()

def save_book_to_list(book_data):
    """
    Add a book to the selections CSV file
    """
    try:
        # Load existing list
        df = load_book_list()
        
        # Check if book is already in the list
        # Convert both IDs to strings to ensure proper comparison
        book_id = str(book_data['id'])
        if not df.empty and book_id in df['id'].astype(str).values:
            return False, "Book is already in your list!"
        
        # Helper function to safely get values
        def safe_get(value, default=''):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return default
            return str(value)
        
        # Prepare book data for CSV
        book_row = {
            'id': safe_get(book_data.get('id', '')),
            'title': safe_get(book_data.get('title', '')),
            'author_names': ', '.join(book_data.get('author_names', [])),
            'release_year': safe_get(book_data.get('release_year', '')),
            'pages': safe_get(book_data.get('pages', '')),
            'rating': safe_get(book_data.get('rating', '')),
            'ratings_count': safe_get(book_data.get('ratings_count', '')),
            'genres': ', '.join(book_data.get('genres', [])),
            'description': safe_get(book_data.get('description', '')),
            'image_url': book_data.get('image', {}).get('url', '') if isinstance(book_data.get('image', {}), dict) else '',
            'added_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Add new book to DataFrame
        new_row = pd.DataFrame([book_row])
        df = pd.concat([df, new_row], ignore_index=True)
        
        # Save to CSV
        df.to_csv(path.join(DATA_DIR, 'book_selections.csv'), index=False)
        return True, "Book added to your list!"
        
    except Exception as e:
        return False, f"Error saving book: {str(e)}"

def load_selection_history():
    """
    Load the selection history from CSV file
    """
    try:
        df = pd.read_csv(path.join(DATA_DIR, 'selection_history.csv'))
        return df
    except FileNotFoundError:
        # Create empty DataFrame with required columns if file doesn't exist
        columns = ['selection_date', 'book_id', 'title', 'author_names', 'genres', 
                  'release_year', 'pages', 'rating', 'selection_round']
        df = pd.DataFrame(columns=columns)
        return df
    except Exception as e:
        st.error(f"Error loading selection history: {str(e)}")
        return pd.DataFrame()

def get_last_selection():
    """
    Get the most recent book selection from history
    """
    history_df = load_selection_history()
    if history_df.empty:
        return None
    
    # Sort by selection_round (or selection_date) and get the last one
    last_selection = history_df.sort_values('selection_round', ascending=False).iloc[0]
    return last_selection

def get_primary_genre(genres_string):
    """
    Extract the primary (first) genre from a comma-separated genres string
    """
    if pd.isna(genres_string) or genres_string == '':
        return ''
    genres = [g.strip() for g in str(genres_string).split(',')]
    return genres[0] if genres else ''

def get_eligible_books_for_selection():
    """
    Get books eligible for random selection (filtering out previous selections, same author, same genre)
    """
    current_books = load_book_list()
    if current_books.empty:
        return current_books, "No books in your list"
    
    history_df = load_selection_history()
    
    # If no history, all books are eligible
    if history_df.empty:
        return current_books, f"All {len(current_books)} books eligible (no previous selections)"
    
    # Get the last selection
    last_selection = get_last_selection()
    last_author = last_selection['author_names']
    last_genre = get_primary_genre(last_selection['genres'])
    
    # Filter out books
    eligible_books = current_books.copy()
    
    # 1. Remove previously selected books
    selected_book_ids = set(history_df['book_id'].tolist())
    eligible_books = eligible_books[~eligible_books['id'].isin(selected_book_ids)]
    
    # 2. Remove books by same author as last selection
    eligible_books = eligible_books[eligible_books['author_names'] != last_author]
    
    # 3. Remove books with same primary genre as last selection
    if last_genre:
        eligible_books = eligible_books[eligible_books['genres'].apply(get_primary_genre) != last_genre]
    
    status_msg = f"{len(eligible_books)} books eligible"
    if len(eligible_books) < len(current_books):
        filtered_out = len(current_books) - len(eligible_books)
        status_msg += f" ({filtered_out} filtered out: previous selections, same author '{last_author}', same genre '{last_genre}')"
    
    return eligible_books, status_msg

def select_random_book():
    """
    Select a random book from eligible books
    """
    eligible_books, status = get_eligible_books_for_selection()
    
    if eligible_books.empty:
        return None, status
    
    # Select random book
    selected_book = eligible_books.sample(n=1).iloc[0]
    return selected_book.to_dict(), status

def save_book_selection(book_data):
    """
    Save a book selection to the history
    """
    try:
        history_df = load_selection_history()
        
        # Determine the next round number
        next_round = 1 if history_df.empty else history_df['selection_round'].max() + 1
        
        # Create new selection record
        selection_row = {
            'selection_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'book_id': book_data['id'],
            'title': book_data['title'],
            'author_names': book_data['author_names'],
            'genres': book_data['genres'],
            'release_year': book_data.get('release_year', ''),
            'pages': book_data.get('pages', ''),
            'rating': book_data.get('rating', ''),
            'selection_round': next_round
        }
        
        # Add new selection to DataFrame
        new_row = pd.DataFrame([selection_row])
        history_df = pd.concat([history_df, new_row], ignore_index=True)
        
        # Save to CSV
        history_df.to_csv(path.join(DATA_DIR, 'selection_history.csv'), index=False)
        return True, f"Book selected for Round {next_round}!"
        
    except Exception as e:
        return False, f"Error saving selection: {str(e)}"

def generate_pdf_data(book_list_df):
    """
    Generate PDF data for the book list
    """
    buffer = BytesIO()
    # Use landscape orientation for better table layout
    from reportlab.lib.pagesizes import landscape
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), topMargin=0.5*inch)
    
    # Get styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], 
                                 fontSize=18, spaceAfter=20, alignment=1)  # Center aligned
    
    # Build PDF content
    story = []
    
    # Title
    title = Paragraph("Book Club Selections", title_style)
    story.append(title)
    story.append(Spacer(1, 20))
    
    # Date
    date_text = f"Generated on: {datetime.now().strftime('%B %d, %Y')}"
    story.append(Paragraph(date_text, styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Create table data
    table_data = [['Title', 'Author(s)', 'Year', 'Pages', 'Rating']]
    
    for _, book in book_list_df.iterrows():
        row = [
            str(book['title'])[:40] + '...' if len(str(book['title'])) > 40 else str(book['title']),
            str(book['author_names'])[:30] + '...' if len(str(book['author_names'])) > 30 else str(book['author_names']),
            str(int(book['release_year'])) if pd.notna(book['release_year']) else '',
            str(int(book['pages'])) if pd.notna(book['pages']) else '',
            f"{book['rating']:.1f}" if pd.notna(book['rating']) else ''
        ]
        table_data.append(row)
    
    # Create and style table with wider columns for landscape layout
    table = Table(table_data, colWidths=[4*inch, 3*inch, 1*inch, 1*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
    ]))
    
    story.append(table)
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def render_floating_selection_box():
    """
    Render a floating selection summary with functional action buttons
    """
    if 'selected_books' not in st.session_state or not st.session_state.selected_books:
        return
    
    selected_books = st.session_state.selected_books
    selected_count = len(selected_books)
    
    # Create a floating box with functional buttons using Streamlit sidebar
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🎯 Quick Actions")
        
        # Show selection summary
        selected_titles = [book.get('title', 'Unknown') for book in selected_books.values()]
        
        if selected_count <= 3:
            titles_text = ', '.join(selected_titles)
        else:
            titles_text = f"{', '.join(selected_titles[:2])}, and {selected_count-2} more"
        
        st.success(f"📚 {selected_count} book{'s' if selected_count != 1 else ''} selected")
        st.caption(titles_text)
        
        # Action buttons in sidebar
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button("🎉 ADD", key="floating_add_button", type="primary", use_container_width=True):
                added_count = 0
                errors = []
                
                for book_id, book in st.session_state.selected_books.items():
                    success, message = save_book_to_list(book)
                    if success:
                        added_count += 1
                    else:
                        errors.append(f"{book.get('title', 'Unknown')}: {message}")
                
                if added_count > 0:
                    st.toast(f"🎉 Successfully added {added_count} book(s) to your list!", icon="📚")
                    st.balloons()
                
                if errors:
                    for error in errors:
                        st.toast(f"⚠️ {error}", icon="⚠️")
                
                # Clear selections after adding
                st.session_state.selected_books = {}
                # Give toast time to display before rerunning
                time.sleep(1.5)
                st.rerun()
        
        with col2:
            if st.button("❌ CLEAR", key="floating_clear_button", use_container_width=True):
                st.session_state.selected_books = {}
                st.rerun()
        
        st.markdown("---")

def display_book_results(api_response):
    """
    Display book search results
    """
    if not api_response or 'data' not in api_response:
        st.error("No valid data received from API")
        return
    
    search_data = api_response.get('data', {}).get('search', {})
    results = search_data.get('results', {})
    hits = results.get('hits', [])
    
    if not hits:
        st.info("No books found matching your search criteria.")
        return
    
    found_count = results.get('found', len(hits))
    st.success(f"Found {found_count:,} books! Showing first {len(hits)}:")
    
    # Hidden buttons for floating box to trigger (placed at top for easy access)
    if 'selected_books' in st.session_state and st.session_state.selected_books:
        # Create invisible container for hidden buttons
        with st.container():
            st.markdown("""
            <style>
                .hidden-button {
                    position: absolute;
                    left: -9999px;
                    opacity: 0;
                    pointer-events: none;
                }
            </style>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            with col1:
                # Hidden button that floating box "Add All" will trigger
                if st.button("", key="floating_add_all", help="Hidden button triggered by floating box"):
                    added_count = 0
                    errors = []
                    
                    for book_id, book in st.session_state.selected_books.items():
                        success, message = save_book_to_list(book)
                        if success:
                            added_count += 1
                        else:
                            errors.append(f"{book.get('title', 'Unknown')}: {message}")
                    
                    if added_count > 0:
                        st.toast(f"🎉 Successfully added {added_count} book(s) to your list!", icon="📚")
                        st.balloons()
                    
                    if errors:
                        for error in errors:
                            st.toast(f"⚠️ {error}", icon="⚠️")
                    
                    # Clear selections after adding
                    st.session_state.selected_books = {}
                    time.sleep(1.5)
                    st.rerun()
            
            with col2:
                # Hidden button that floating box "Clear" will trigger
                if st.button("", key="floating_clear_all", help="Hidden button triggered by floating box"):
                    st.session_state.selected_books = {}
                    st.rerun()
    
    # Show selected books count and add button at the top (original functionality preserved)
    if 'selected_books' in st.session_state and st.session_state.selected_books:
        selected_count = len(st.session_state.selected_books)
        
        # Create a prominent alert box at the top
        st.info(f"📚 {selected_count} book(s) selected")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            # Show selected book titles briefly
            selected_titles = [book.get('title', 'Unknown') for book in st.session_state.selected_books.values()]
            if len(selected_titles) <= 3:
                st.caption(f"Selected: {', '.join(selected_titles)}")
            else:
                st.caption(f"Selected: {', '.join(selected_titles[:2])}, and {len(selected_titles)-2} more...")
        
        with col2:
            if st.button("🎉 ADD ALL SELECTED BOOKS", type="primary", key="top_add_button"):
                added_count = 0
                errors = []
                
                for book_id, book in st.session_state.selected_books.items():
                    success, message = save_book_to_list(book)
                    if success:
                        added_count += 1
                    else:
                        errors.append(f"{book.get('title', 'Unknown')}: {message}")
                
                if added_count > 0:
                    st.toast(f"🎉 Successfully added {added_count} book(s) to your list!", icon="📚")
                    st.balloons()
                
                if errors:
                    for error in errors:
                        st.toast(f"⚠️ {error}", icon="⚠️")
                
                # Clear selections after adding
                st.session_state.selected_books = {}
                # Give toast time to display before rerunning
                time.sleep(1.5)
                st.rerun()
        
        with col3:
            if st.button("❌ Clear Selection", key="top_clear_button"):
                st.session_state.selected_books = {}
                st.rerun()
        
        st.markdown("---")
    
    for i, hit in enumerate(hits):
        book = hit.get('document', {})
        book_id = book.get('id', f'unknown_{i}')
        
        with st.container():
            col1, col2 = st.columns([1, 3])
            
            with col1:
                # Display book cover if available
                image_data = book.get('image', {})
                image_url = image_data.get('url') if image_data else None
                safe_display_image(image_url, width=150)
                
                # Check if already added (simple check)
                try:
                    existing_df = pd.read_csv(path.join(DATA_DIR, 'book_selections.csv'))
                    already_added = book_id in existing_df['id'].values if not existing_df.empty else False
                except:
                    already_added = False
                
                if already_added:
                    st.success("✅ Added")
                else:
                    # Initialize selected_books if it doesn't exist
                    if 'selected_books' not in st.session_state:
                        st.session_state.selected_books = {}
                    
                    # Use checkbox with proper state management
                    checkbox_key = f"select_{book_id}_{i}"
                    
                    # Check if this book is already selected (for checkbox default value)
                    is_selected = book_id in st.session_state.selected_books
                    
                    # Create checkbox with current selection state
                    checkbox_value = st.checkbox("📚 Select to Add", key=checkbox_key, value=is_selected)
                    
                    # Update session state based on checkbox value
                    if checkbox_value and book_id not in st.session_state.selected_books:
                        # Add to selection
                        st.session_state.selected_books[book_id] = book
                        st.rerun()  # Force immediate rerun to show changes
                    elif not checkbox_value and book_id in st.session_state.selected_books:
                        # Remove from selection
                        del st.session_state.selected_books[book_id]
                        st.rerun()  # Force immediate rerun to show changes
            
            with col2:
                # Book title
                title = book.get('title', 'Unknown Title')
                st.subheader(title)
                
                # Subtitle if available
                if book.get('subtitle'):
                    st.caption(book['subtitle'])
                
                # Authors
                author_names = book.get('author_names', [])
                if author_names:
                    st.write(f"**Author(s):** {', '.join(author_names)}")
                
                # Publication year and pages
                info_items = []
                if book.get('release_year'):
                    info_items.append(f"Published: {int(book['release_year'])}")
                if book.get('pages'):
                    info_items.append(f"Pages: {book['pages']}")
                
                if info_items:
                    st.write(f"**Details:** {' | '.join(info_items)}")
                
                # Rating
                if book.get('rating') and book.get('ratings_count'):
                    rating = book['rating']
                    count = book['ratings_count']
                    st.write(f"**Rating:** ⭐ {rating:.1f}/5 ({count:,} ratings)")
                
                # Genres
                genres = book.get('genres', [])
                if genres:
                    st.write(f"**Genres:** {', '.join(genres)}")
                
                # Series information
                series_names = book.get('series_names', [])
                if series_names:
                    series_info = ', '.join(series_names)
                    if book.get('featured_series_position'):
                        series_info += f" (Book {book['featured_series_position']})"
                    st.write(f"**Series:** {series_info}")
                
                # Description (truncated)
                if book.get('description'):
                    desc = book['description']
                    if len(desc) > 300:
                        desc = desc[:300] + "..."
                    st.write(f"**Description:** {desc}")
                
                # Additional info badges
                info_badges = []
                if book.get('users_count'):
                    info_badges.append(f"📚 {book['users_count']:,} users")
                if book.get('has_audiobook'):
                    info_badges.append("🎧 Audiobook")
                if book.get('has_ebook'):
                    info_badges.append("📱 E-book")
                if book.get('compilation'):
                    info_badges.append("📖 Collection")
                
                if info_badges:
                    st.caption(" • ".join(info_badges))
            
            st.divider()
    
    # Only show bottom section if no books are selected (less clutter)
    if not ('selected_books' in st.session_state and st.session_state.selected_books):
        st.markdown("---")
        st.info("💡 **Tip:** Select books using the checkboxes above. The 'Add Selected Books' button will appear at the top when you make selections!")
    else:
        # Show bottom "Add All Selected Books" button when books are selected
        st.markdown("---")
        st.subheader("📚 Selected Books Actions")
        
        selected_count = len(st.session_state.selected_books)
        selected_titles = [book.get('title', 'Unknown') for book in st.session_state.selected_books.values()]
        
        # Show selected books summary
        st.info(f"📚 {selected_count} book(s) selected for adding to your list")
        if len(selected_titles) <= 5:
            st.caption(f"Selected: {', '.join(selected_titles)}")
        else:
            st.caption(f"Selected: {', '.join(selected_titles[:3])}, and {len(selected_titles)-3} more...")
        
        # Action buttons
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button("🎉 ADD ALL SELECTED BOOKS", type="primary", key="bottom_add_button", use_container_width=True):
                added_count = 0
                errors = []
                
                for book_id, book in st.session_state.selected_books.items():
                    success, message = save_book_to_list(book)
                    if success:
                        added_count += 1
                    else:
                        errors.append(f"{book.get('title', 'Unknown')}: {message}")
                
                if added_count > 0:
                    st.toast(f"🎉 Successfully added {added_count} book(s) to your list!", icon="📚")
                    st.balloons()
                
                if errors:
                    for error in errors:
                        st.toast(f"⚠️ {error}", icon="⚠️")
                
                # Clear selections after adding
                st.session_state.selected_books = {}
                # Give toast time to display before rerunning
                time.sleep(1.5)
                st.rerun()
        
        with col2:
            if st.button("❌ Clear All Selections", key="bottom_clear_button", use_container_width=True):
                st.session_state.selected_books = {}
                st.rerun()

# Initialize session state
if 'show_full_list' not in st.session_state:
    st.session_state.show_full_list = False
if 'added_books' not in st.session_state:
    st.session_state.added_books = set()
if 'show_add_confirmation' not in st.session_state:
    st.session_state.show_add_confirmation = False
if 'book_to_add' not in st.session_state:
    st.session_state.book_to_add = None
if 'show_random_selection' not in st.session_state:
    st.session_state.show_random_selection = False
if 'random_selected_book' not in st.session_state:
    st.session_state.random_selected_book = None
if 'selected_books' not in st.session_state:
    st.session_state.selected_books = {}

# Book list section in sidebar
st.sidebar.header("Current Book List")

try:
    book_list_df = load_book_list()
    
    if not book_list_df.empty:
        st.sidebar.write(f"**{len(book_list_df)} books chosen**")
        
        # Show recent additions in sidebar
        if len(book_list_df) > 0:
            recent_books = book_list_df.tail(3)  # Show last 3 added
            for _, book in recent_books.iterrows():
                if book['author_names']:
                    st.sidebar.caption(f"📖 {book['title']} by {book['author_names']}")
                else:
                    st.sidebar.caption(f"📖 {book['title']}")
        
        # Button to view full list
        if st.sidebar.button("View Full List"):
            st.session_state.show_full_list = True
            st.rerun()
    else:
        st.sidebar.write("No books chosen yet")
        st.sidebar.write("Search and add some books to see them here!")
        
except Exception as e:
    st.sidebar.error(f"Error loading book list: {str(e)}")
    st.sidebar.write("No books chosen yet")

# Add floating selection box in sidebar for quick actions
render_floating_selection_box()

# Navigation
st.sidebar.markdown("---")

# Search Navigation - Always visible

if st.sidebar.button("📚 Go to Search", type="primary", use_container_width=True):
    st.session_state.show_full_list = False
    # Clear any existing selections when going to search
    if 'selected_books' in st.session_state:
        st.session_state.selected_books = {}
    st.rerun()

if st.sidebar.button("📋 View My Book List", use_container_width=True):
    st.session_state.show_full_list = True
    st.rerun()

# Random Selection Section
st.sidebar.markdown("---")
st.sidebar.markdown("### 🎲 Random Selection")

# Show last selection info
try:
    last_selection = get_last_selection()
    if last_selection is not None:
        st.sidebar.caption(f"**Last Pick:** {last_selection['title']}")
        st.sidebar.caption(f"**Author:** {last_selection['author_names']}")
        st.sidebar.caption(f"**Genre:** {get_primary_genre(last_selection['genres'])}")
    else:
        st.sidebar.caption("No previous selections")
except:
    st.sidebar.caption("Error loading selection history")

# Check eligible books
try:
    eligible_books, status = get_eligible_books_for_selection()
    st.sidebar.caption(status)
    
    # Random selection button
    if len(eligible_books) > 0:
        if st.sidebar.button("🎲 Pick Random Book", type="secondary", use_container_width=True):
            st.session_state.show_random_selection = True
            st.rerun()
    else:
        st.sidebar.info("No eligible books for selection")
        
except Exception as e:
    st.sidebar.error(f"Selection error: {str(e)}")

# Selection History Management
try:
    history_df = load_selection_history()
    if not history_df.empty:
        st.sidebar.markdown("#### 📜 Selection History")
        
        # Remove last selection button
        if st.sidebar.button("🔙 Remove Last Selection", use_container_width=True, help="Remove the most recent book selection"):
            success, message = remove_last_selection()
            if success:
                st.toast(f"🗑️ {message}", icon="✅")
                st.rerun()
            else:
                st.toast(f"❌ {message}", icon="⚠️")
        
        # Clear all selections button (with confirmation)
        if 'confirm_clear_selections' not in st.session_state:
            st.session_state.confirm_clear_selections = False
        
        if not st.session_state.confirm_clear_selections:
            if st.sidebar.button("🗑️ Clear All Selections", use_container_width=True, help="Remove all selection history"):
                st.session_state.confirm_clear_selections = True
                st.rerun()
        else:
            st.sidebar.warning("⚠️ This will delete ALL selection history!")
            col1, col2 = st.sidebar.columns(2)
            with col1:
                if st.button("✅ Confirm", key="confirm_clear", use_container_width=True):
                    success, message = clear_all_selections()
                    if success:
                        st.toast(f"🧹 {message}", icon="✅")
                        st.session_state.confirm_clear_selections = False
                        st.rerun()
                    else:
                        st.toast(f"❌ {message}", icon="⚠️")
                        st.session_state.confirm_clear_selections = False
            with col2:
                if st.button("❌ Cancel", key="cancel_clear", use_container_width=True):
                    st.session_state.confirm_clear_selections = False
                    st.rerun()

except Exception as e:
    st.sidebar.error(f"Selection history error: {str(e)}")

st.sidebar.markdown("---")



# Test basic interactivity (comment out if not needed)
# st.sidebar.markdown("### 🧪 Test Section")
# test_button_enabled = True  # Set to True if you want to test

# if test_button_enabled and st.sidebar.button("Test Button - Click Me!"):
#     st.sidebar.success("✅ Button works!")
#     st.sidebar.balloons()

# test_checkbox = st.sidebar.checkbox("Test checkbox")
# if test_checkbox:
#     st.sidebar.write("✅ Checkbox works!")

# Manual book entry as backup
st.sidebar.markdown("### ➕ Manual Entry")
with st.sidebar.form("manual_entry"):
    manual_title = st.text_input("Book Title")
    manual_author = st.text_input("Author")
    manual_year = st.number_input("Year", min_value=1000, max_value=2030, step=1, value=2024)
    
    if st.form_submit_button("Add Manually"):
        if manual_title and manual_author:
            manual_book = {
                'id': f"manual_{manual_title.replace(' ', '_').lower()}",
                'title': manual_title,
                'author_names': [manual_author],
                'release_year': manual_year,
                'pages': '',
                'rating': '',
                'ratings_count': '',
                'genres': ['Manual Entry'],
                'description': 'Manually added book',
                'image': {}
            }
            success, message = save_book_to_list(manual_book)
            if success:
                st.toast("📚 Book added manually!", icon="✅")
                # Give toast time to display before rerunning
                time.sleep(1.5)
                st.rerun()
            else:
                st.sidebar.error(f"❌ {message}")
        else:
            st.sidebar.warning("Please enter title and author")
# Cleanup Section
st.sidebar.markdown("### 🧹 Maintenance")
if st.sidebar.button("🗑️ Remove Duplicate Books", use_container_width=True, help="Clean up any duplicate entries in your book list"):
    removed_count = clean_duplicate_books()
    if removed_count > 0:
        st.toast(f"🧹 Removed {removed_count} duplicate book(s)!", icon="✅")
        st.rerun()
    else:
        st.toast("✅ No duplicates found!", icon="🧹")

# st.sidebar.markdown("---")

# Header with logo and title right next to each other
st.markdown(f"""
<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px;">
    <img src="data:image/png;base64,{base64.b64encode(open(path.join(DATA_DIR, 'book_club_logo.png'), 'rb').read()).decode()}" 
         width="200" style="vertical-align: middle;">
    <div>
        <h3 style="margin: 0; padding: 0;">Book Club Selections</h3>
        <p style="margin: 0; padding: 0; font-style: italic; color: #666;">Find and manage your book club's reading selections</p>
    </div>
</div>
""", unsafe_allow_html=True)
if st.session_state.show_add_confirmation and st.session_state.book_to_add:
    # Book addition confirmation page
    st.header("📚 Add Book to Your List")
    
    book = st.session_state.book_to_add
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # Display book cover
        image_data = book.get('image', {})
        image_url = image_data.get('url') if image_data else None
        safe_display_image(image_url, width=200)
    
    with col2:
        st.subheader(book.get('title', 'Unknown Title'))
        
        if book.get('subtitle'):
            st.caption(book['subtitle'])
        
        if book.get('author_names'):
            st.write(f"**Author(s):** {', '.join(book['author_names'])}")
        
        info_items = []
        if book.get('release_year'):
            info_items.append(f"Published: {int(book['release_year'])}")
        if book.get('pages'):
            info_items.append(f"Pages: {book['pages']}")
        
        if info_items:
            st.write(f"**Details:** {' | '.join(info_items)}")
        
        if book.get('rating') and book.get('ratings_count'):
            rating = book['rating']
            count = book['ratings_count']
            st.write(f"**Rating:** ⭐ {rating:.1f}/5 ({count:,} ratings)")
        
        if book.get('genres'):
            st.write(f"**Genres:** {', '.join(book['genres'])}")
    
    if book.get('description'):
        st.write("**Description:**")
        st.write(book['description'])
    
    st.markdown("---")
    # Action buttons
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        if st.button("✅ Yes, Add This Book", type="primary", use_container_width=True):
            success, message = save_book_to_list(book)
            if success:
                st.toast(f"📚 {message}", icon="✅")
                st.balloons()
                # Clear the confirmation state
                st.session_state.show_add_confirmation = False
                st.session_state.book_to_add = None
                # Give toast time to display before rerunning
                time.sleep(1.5)
                st.rerun()
            else:
                st.error(f"❌ {message}")
    
    with col2:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state.show_add_confirmation = False
            st.session_state.book_to_add = None
            st.rerun()
    
    with col3:
        if st.button("🔍 Back to Search", use_container_width=True):
            st.session_state.show_add_confirmation = False
            st.session_state.book_to_add = None
            st.rerun()

elif st.session_state.show_random_selection:
    # Random selection page
    st.header("🎲 Random Book Selection")
    
    # Show last selection context
    try:
        last_selection = get_last_selection()
        if last_selection is not None:
            st.info(f"**Previous Selection:** {last_selection['title']} by {last_selection['author_names']} ({get_primary_genre(last_selection['genres'])})")
    except:
        pass
    
    # Get eligible books and show status
    try:
        eligible_books, status = get_eligible_books_for_selection()
        st.write(f"**Status:** {status}")
        
        if len(eligible_books) == 0:
            st.warning("⚠️ No books are eligible for selection with current filtering rules.")
            st.info("All books have been previously selected, or they have the same author/genre as the last selection.")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔍 Back to Search", use_container_width=True):
                    st.session_state.show_random_selection = False
                    st.rerun()
            with col2:
                if st.button("📋 View Book List", use_container_width=True):
                    st.session_state.show_random_selection = False
                    st.session_state.show_full_list = True
                    st.rerun()
        
        else:
            # Show eligible books preview
            st.subheader(f"📚 {len(eligible_books)} Eligible Books")
            
            # Preview first few eligible books
            preview_count = min(3, len(eligible_books))
            for i, (_, book) in enumerate(eligible_books.head(preview_count).iterrows()):
                st.caption(f"• {book['title']} by {book['author_names']} ({get_primary_genre(book['genres'])})")
            
            if len(eligible_books) > preview_count:
                st.caption(f"... and {len(eligible_books) - preview_count} more")
            
            st.markdown("---")
            
            # Random selection button
            col1, col2, col3 = st.columns([2, 1, 2])
            
            with col2:
                if st.button("🎲 SELECT RANDOM BOOK", type="primary", use_container_width=True):
                    selected_book, selection_status = select_random_book()
                    if selected_book:
                        st.session_state.random_selected_book = selected_book
                        st.rerun()
                    else:
                        st.error(f"Selection failed: {selection_status}")
            
            # Show selected book if one was chosen
            if st.session_state.random_selected_book:
                st.success("🎉 **Book Selected!**")
                
                selected_book = st.session_state.random_selected_book
                
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    # Display book cover if available
                    safe_display_image(selected_book.get('image_url'), width=200, fallback_text="📖 Cover not available")
                
                with col2:
                    st.markdown(f"### {selected_book['title']}")
                    st.write(f"**Author:** {selected_book['author_names']}")
                    
                    info_items = []
                    if selected_book.get('release_year'):
                        info_items.append(f"Published: {int(selected_book['release_year'])}")
                    if selected_book.get('pages'):
                        info_items.append(f"Pages: {selected_book['pages']}")
                    
                    if info_items:
                        st.write(f"**Details:** {' | '.join(info_items)}")
                    
                    if selected_book.get('rating'):
                        rating = selected_book['rating']
                        stars = "⭐" * int(rating)
                        st.write(f"**Rating:** {rating:.1f}/5 {stars}")
                    
                    if selected_book.get('genres'):
                        st.write(f"**Genres:** {selected_book['genres']}")
                
                if selected_book.get('description'):
                    st.write("**Description:**")
                    st.write(selected_book['description'])
                
                st.markdown("---")
                
                # Confirmation buttons
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if st.button("✅ Confirm Selection", type="primary", use_container_width=True):
                        success, message = save_book_selection(selected_book)
                        if success:
                            st.toast(f"🎲 {message}", icon="✅")
                            st.balloons()
                            # Reset state
                            st.session_state.show_random_selection = False
                            st.session_state.random_selected_book = None
                            # Give toast time to display before rerunning
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error(message)
                
                with col2:
                    if st.button("🎲 Pick Different Book", use_container_width=True):
                        st.session_state.random_selected_book = None
                        st.rerun()
                
                with col3:
                    if st.button("❌ Cancel", use_container_width=True):
                        st.session_state.show_random_selection = False
                        st.session_state.random_selected_book = None
                        st.rerun()
            
            else:
                # Navigation options when no book selected yet
                st.markdown("---")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔍 Back to Search", use_container_width=True):
                        st.session_state.show_random_selection = False
                        st.rerun()
                with col2:
                    if st.button("📋 View Book List", use_container_width=True):
                        st.session_state.show_random_selection = False
                        st.session_state.show_full_list = True
                        st.rerun()
        
    except Exception as e:
        st.error(f"Error during random selection: {str(e)}")
        st.button("🔍 Back to Search")

elif not st.session_state.show_full_list:
    # Search interface
    st.header("Search for Books")
    
    # Add helpful info about field-specific searching
    with st.expander("💡 Search Tips", expanded=False):
        st.markdown("""
        **Field-Specific Search:** Each field searches within that specific book attribute:
        - **Author**: Searches only in author names
        - **Title**: Searches only in book titles  
        - **Genre**: Searches only in book genres
        
        **Examples:**
        - Author: "Stephen King" → finds books by Stephen King specifically
        - Genre: "Horror" → finds books categorized as Horror genre (not books with "horror" in title)
        - Title: "The Shining" → finds books with "The Shining" in the title
        
        **Multiple Fields:** You can combine fields (e.g., Author + Genre) to narrow results.
        """)

    # Create columns for better layout
    col1, col2, col3 = st.columns(3)

    # Use session state keys to allow clearing of input fields
    search_key_suffix = st.session_state.get('search_form_key', 0)

    with col1:
        author_search = st.text_input(
            "Author",
            placeholder="e.g., Stephen King",
            help="Search specifically in author names only",
            key=f"author_search_{search_key_suffix}"
        )

    with col2:
        title_search = st.text_input(
            "Title", 
            placeholder="e.g., The Shining",
            help="Search specifically in book titles only",
            key=f"title_search_{search_key_suffix}"
        )

    with col3:
        genre_search = st.text_input(
            "Genre",
            placeholder="e.g., Horror",
            help="Search specifically in book genres only (not titles or descriptions)",
            key=f"genre_search_{search_key_suffix}"
        )

    # Search and Clear buttons
    col1, col2 = st.columns([3, 1])
    
    with col1:
        search_button = st.button("Search Books", type="primary", use_container_width=True)
    
    with col2:
        if st.button("🗑️ Clear Search", use_container_width=True, help="Clear search fields and results"):
            # Clear search results
            if 'last_search_results' in st.session_state:
                del st.session_state.last_search_results
            if 'last_search_terms' in st.session_state:
                del st.session_state.last_search_terms
            if 'selected_books' in st.session_state:
                del st.session_state.selected_books
            
            # Reset search form by changing the key suffix (forces new text inputs)
            current_key = st.session_state.get('search_form_key', 0)
            st.session_state.search_form_key = current_key + 1
            
            st.rerun()

    # Search results
    if search_button:
        if author_search or title_search or genre_search:
            with st.spinner("🔍 Searching... This may take a few seconds"):
                # Show immediate feedback
                progress_text = st.empty()
                progress_text.text("⚡ Searching book database...")
                
                # Call the search function
                search_results = search_hardcover_api(
                    author=author_search if author_search else None,
                    title=title_search if title_search else None,
                    genre=genre_search if genre_search else None
                )
                
                progress_text.empty()  # Clear progress text
                
                if search_results:
                    # Store search results in session state so they persist across reloads
                    st.session_state.last_search_results = search_results
                    st.session_state.last_search_terms = {
                        'author': author_search,
                        'title': title_search,
                        'genre': genre_search
                    }
                else:
                    st.error("Search failed. Please check your connection or try again.")
        else:
            st.warning("Please enter at least one search criteria.")
    
    # Display search results if they exist in session state
    if 'last_search_results' in st.session_state:
        # Show what was searched for
        if 'last_search_terms' in st.session_state:
            terms = st.session_state.last_search_terms
            if terms['author'] or terms['title'] or terms['genre']:
                st.subheader("Current Search Results:")
                search_criteria = []
                if terms['author']:
                    search_criteria.append(f"**Author:** {terms['author']}")
                if terms['title']:
                    search_criteria.append(f"**Title:** {terms['title']}")
                if terms['genre']:
                    search_criteria.append(f"**Genre:** {terms['genre']}")
                st.write(" | ".join(search_criteria))
        
        # Top action buttons
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button("🔍 New Search", key="top_new_search", use_container_width=True):
                # Clear search results and go back to search form
                if 'last_search_results' in st.session_state:
                    del st.session_state.last_search_results
                if 'last_search_terms' in st.session_state:
                    del st.session_state.last_search_terms
                if 'selected_books' in st.session_state:
                    del st.session_state.selected_books
                st.rerun()
        
        with col2:
            if st.button("🗑️ Clear Search Results", key="top_clear_search", use_container_width=True):
                if 'last_search_results' in st.session_state:
                    del st.session_state.last_search_results
                if 'last_search_terms' in st.session_state:
                    del st.session_state.last_search_terms
                if 'selected_books' in st.session_state:
                    del st.session_state.selected_books
                st.rerun()
        
        st.markdown("---")
        
        # Display the results
        display_book_results(st.session_state.last_search_results)
        
        # Bottom action buttons (after all results)
        st.markdown("---")
        st.subheader("🔍 Search Actions")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button("🔍 Start New Search", key="bottom_new_search", type="primary", use_container_width=True):
                # Clear search results and go back to search form
                if 'last_search_results' in st.session_state:
                    del st.session_state.last_search_results
                if 'last_search_terms' in st.session_state:
                    del st.session_state.last_search_terms
                if 'selected_books' in st.session_state:
                    del st.session_state.selected_books
                st.rerun()
        
        with col2:
            if st.button("📋 View My Book List", key="bottom_view_list", use_container_width=True):
                st.session_state.show_full_list = True
                st.rerun()

else:
    st.header("📚 Your Book Club Selections")
    
    book_list_df = load_book_list()
    
    if not book_list_df.empty:
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            st.write(f"**{len(book_list_df)} books in your selection list**")
        
        with col2:
            # Always show remove button when there are books, but enable/disable based on selections
            if hasattr(st.session_state, 'books_to_remove') and st.session_state.books_to_remove:
                button_label = f"🗑️ Remove {len(st.session_state.books_to_remove)} Books"
                button_disabled = False
                button_type = "secondary"
            else:
                button_label = "🗑️ Remove Selected Books"
                button_disabled = True
                button_type = "secondary"
            
            if st.button(button_label, key="top_remove_button", type=button_type, 
                        use_container_width=True, disabled=button_disabled):
                # Remove books from DataFrame
                updated_df = book_list_df[~book_list_df['id'].isin(st.session_state.books_to_remove)]
                updated_df.to_csv(path.join(DATA_DIR, 'book_selections.csv'), index=False)
                
                # Update session state
                for book_id in st.session_state.books_to_remove:
                    st.session_state.added_books.discard(book_id)
                
                removed_count = len(st.session_state.books_to_remove)
                st.session_state.books_to_remove = set()
                
                st.success(f"✅ Removed {removed_count} book(s) from your list!")
                st.rerun()
        
        with col3:
            if st.button("Hide List", use_container_width=True):
                st.session_state.show_full_list = False
                st.rerun()
        
        # Show count of selected books for removal at top if any are selected
        if hasattr(st.session_state, 'books_to_remove') and st.session_state.books_to_remove:
            st.info(f"🗑️ {len(st.session_state.books_to_remove)} book(s) marked for removal")
        
        # Display books in a nice format
        for idx, book in book_list_df.iterrows():
            with st.container():
                col1, col2, col3 = st.columns([1, 3, 1])
                
                with col1:
                    safe_display_image(book['image_url'], width=100, fallback_text="📚")
                
                with col2:
                    st.subheader(book['title'])
                    if book['author_names']:
                        st.write(f"**Author(s):** {book['author_names']}")
                    
                    info_items = []
                    if book['release_year'] and pd.notna(book['release_year']):
                        info_items.append(f"Published: {int(book['release_year'])}")
                    if book['pages'] and pd.notna(book['pages']):
                        info_items.append(f"Pages: {book['pages']}")
                    
                    if info_items:
                        st.write(f"**Details:** {' | '.join(info_items)}")
                    
                    if (book['rating'] and pd.notna(book['rating']) and 
                        book['ratings_count'] and pd.notna(book['ratings_count'])):
                        try:
                            rating = float(book['rating'])
                            count = int(book['ratings_count'])
                            st.write(f"**Rating:** ⭐ {rating:.1f}/5 ({count:,} ratings)")
                        except (ValueError, TypeError):
                            pass  # Skip rating display if conversion fails
                    
                    if book['genres']:
                        st.write(f"**Genres:** {book['genres']}")
                    
                    st.caption(f"Added: {book['added_date']}")
                
                with col3:
                    # Remove checkbox - better than button
                    remove_key = f"remove_check_list_{book['id']}_{idx}"
                    
                    # Initialize books_to_remove if it doesn't exist
                    if 'books_to_remove' not in st.session_state:
                        st.session_state.books_to_remove = set()
                    
                    # Check if this book is currently selected for removal
                    is_marked_for_removal = book['id'] in st.session_state.books_to_remove
                    
                    # Create checkbox with current state
                    checkbox_value = st.checkbox("🗑️ Mark for removal", key=remove_key, value=is_marked_for_removal)
                    
                    # Update session state based on checkbox value
                    if checkbox_value and book['id'] not in st.session_state.books_to_remove:
                        # Add to removal list
                        st.session_state.books_to_remove.add(book['id'])
                        st.rerun()  # Force immediate rerun to update top button
                    elif not checkbox_value and book['id'] in st.session_state.books_to_remove:
                        # Remove from removal list
                        st.session_state.books_to_remove.discard(book['id'])
                        st.rerun()  # Force immediate rerun to update top button
                
                st.divider()
        
        # Remove selected books button
        if hasattr(st.session_state, 'books_to_remove') and st.session_state.books_to_remove:
            st.markdown("---")
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.write(f"**{len(st.session_state.books_to_remove)} book(s) marked for removal**")
            
            with col2:
                if st.button("🗑️ Remove Selected Books", type="secondary"):
                    # Remove books from DataFrame
                    updated_df = book_list_df[~book_list_df['id'].isin(st.session_state.books_to_remove)]
                    updated_df.to_csv(path.join(DATA_DIR, 'book_selections.csv'), index=False)
                    
                    # Update session state
                    for book_id in st.session_state.books_to_remove:
                        st.session_state.added_books.discard(book_id)
                    
                    removed_count = len(st.session_state.books_to_remove)
                    st.session_state.books_to_remove = set()
                    
                    st.success(f"✅ Removed {removed_count} book(s) from your list!")
                    st.rerun()
        
        # Export options
        st.subheader("📥 Export Options")
        
        # Prepare all download data
        csv_data = book_list_df.to_csv(index=False)
        
        text_list = []
        for _, book in book_list_df.iterrows():
            text_list.append(f"• {book['title']} by {book['author_names']}")
        text_data = "Book Club Selections:\n\n" + "\n".join(text_list)
        
        # Responsive layout - stacked vertically for better mobile experience
        st.download_button(
            label="📊 Download as Excel/CSV",
            data=csv_data,
            file_name="book_club_selections.csv",
            mime="text/csv",
            use_container_width=True,
            help="Download your book list as a spreadsheet file"
        )
        
        st.download_button(
            label="📝 Download as Text List",
            data=text_data,
            file_name="book_club_selections.txt",
            mime="text/plain",
            use_container_width=True,
            help="Download as a simple text list"
        )
            
        try:
            pdf_data = generate_pdf_data(book_list_df)
            st.download_button(
                label="📄 Download as PDF",
                data=pdf_data,
                file_name="book_club_selections.pdf",
                mime="application/pdf",
                use_container_width=True,
                help="Download as a formatted PDF document"
            )
        except Exception as e:
            st.error(f"PDF generation error: {str(e)}")
    else:
        st.info("No books in your selection list yet. Search and add some books!")
        if st.button("Back to Search"):
            st.session_state.show_full_list = False
            st.rerun()
