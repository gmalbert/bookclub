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
            
        st.error("🔐 API token not found. Please configure HARDCOVER_API_TOKEN in Streamlit secrets or environment variables.")
        st.info("For deployment, add your token to Streamlit Cloud secrets. For local development, set the HARDCOVER_API_TOKEN environment variable or use token.txt")
        return None
        
    except Exception as e:
        st.error(f"Error loading API token: {str(e)}")
        return None

def search_hardcover_api(author=None, title=None, genre=None):
    """
    Search Hardcover API for books based on criteria using the search endpoint
    """
    token = load_api_token()
    if not token:
        return None
    
    headers = {
        'Authorization': token,
        'Content-Type': 'application/json'
    }
    
    api_url = "https://api.hardcover.app/v1/graphql"
    
    # Build search query - combine all search terms
    search_terms = []
    if title:
        search_terms.append(title)
    if author:
        search_terms.append(author)
    if genre:
        search_terms.append(genre)
    
    search_query = " ".join(search_terms)
    
    # Use the Hardcover search endpoint with proper GraphQL query
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
        "perPage": 20,
        "page": 1
    }
    
    payload = {
        "query": query,
        "variables": variables
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {str(e)}")
        return None
    except json.JSONDecodeError as e:
        st.error(f"Failed to parse API response: {str(e)}")
        return None

def load_book_list():
    """
    Load the current book list from CSV file
    """
    try:
        df = pd.read_csv('book_selections.csv')
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
        if not df.empty and book_data['id'] in df['id'].values:
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
        df.to_csv('book_selections.csv', index=False)
        return True, "Book added to your list!"
        
    except Exception as e:
        return False, f"Error saving book: {str(e)}"

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

def display_book_results(api_response):
    """
    Display book search results from Hardcover search API
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
    
    # Show selected books count and add button at the top
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
                    st.success(f"🎉 Successfully added {added_count} book(s) to your list!")
                    st.balloons()
                
                if errors:
                    for error in errors:
                        st.warning(f"⚠️ {error}")
                
                # Clear selections after adding
                st.session_state.selected_books = {}
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
                if image_data and image_data.get('url'):
                    st.image(image_data['url'], width=150)
                else:
                    st.write("📚 No cover")
                
                # Check if already added (simple check)
                try:
                    existing_df = pd.read_csv('book_selections.csv')
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

# Initialize session state
if 'show_full_list' not in st.session_state:
    st.session_state.show_full_list = False
if 'added_books' not in st.session_state:
    st.session_state.added_books = set()
if 'show_add_confirmation' not in st.session_state:
    st.session_state.show_add_confirmation = False
if 'book_to_add' not in st.session_state:
    st.session_state.book_to_add = None

# Book list section in sidebar
st.sidebar.header("Current Book List")

try:
    book_list_df = load_book_list()
    # st.sidebar.write(f"Debug: DataFrame shape: {book_list_df.shape}")
    # st.sidebar.write(f"Debug: DataFrame empty: {book_list_df.empty}")
    
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
                st.sidebar.success("✅ Book added manually!")
                st.rerun()
            else:
                st.sidebar.error(f"❌ {message}")
        else:
            st.sidebar.warning("Please enter title and author")

# Header with logo and title right next to each other
st.markdown(f"""
<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px;">
    <img src="data:image/png;base64,{base64.b64encode(open(path.join(DATA_DIR, 'book_club_logo.png'), 'rb').read()).decode()}" 
         width="200" style="vertical-align: middle;">
    <div>
        <h1 style="margin: 0; padding: 0;">Book Club Selections</h1>
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
        if image_data and image_data.get('url'):
            st.image(image_data['url'], width=200)
        else:
            st.write("📚 No cover available")
    
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
                st.success(f"✅ {message}")
                st.balloons()
                # Clear the confirmation state
                st.session_state.show_add_confirmation = False
                st.session_state.book_to_add = None
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

elif not st.session_state.show_full_list:
    # Search interface
    st.header("Search for Books")

    # Create columns for better layout
    col1, col2, col3 = st.columns(3)

    with col1:
        author_search = st.text_input(
            "Author",
            placeholder="Enter author name...",
            help="Search by author name"
        )

    with col2:
        title_search = st.text_input(
            "Title", 
            placeholder="Enter book title...",
            help="Search by book title"
        )

    with col3:
        genre_search = st.text_input(
            "Genre",
            placeholder="Enter genre...",
            help="Search by genre (e.g., Fiction, Mystery, Romance)"
        )

    # Search button
    search_button = st.button("Search Books", type="primary")

    # Display search criteria if any are entered
    if author_search or title_search or genre_search:
        st.subheader("Search Criteria:")
        search_criteria = []
        if author_search:
            search_criteria.append(f"**Author:** {author_search}")
        if title_search:
            search_criteria.append(f"**Title:** {title_search}")
        if genre_search:
            search_criteria.append(f"**Genre:** {genre_search}")
        
        st.write(" | ".join(search_criteria))

    # Search results
    if search_button:
        if author_search or title_search or genre_search:
            with st.spinner("🔍 Searching Hardcover API..."):
                # Call the search function
                search_results = search_hardcover_api(
                    author=author_search if author_search else None,
                    title=title_search if title_search else None,
                    genre=genre_search if genre_search else None
                )
                
                if search_results:
                    # Store search results in session state so they persist across reloads
                    st.session_state.last_search_results = search_results
                    st.session_state.last_search_terms = {
                        'author': author_search,
                        'title': title_search,
                        'genre': genre_search
                    }
                else:
                    st.error("Failed to perform search. Please check your API token or try again.")
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
                updated_df.to_csv('book_selections.csv', index=False)
                
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
                    image_url = book['image_url']
                    if image_url and isinstance(image_url, str) and image_url.strip():
                        try:
                            st.image(image_url, width=100)
                        except:
                            st.write("📚")
                    else:
                        st.write("📚")
                
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
                    remove_key = f"remove_check_{book['id']}"
                    
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
                    updated_df.to_csv('book_selections.csv', index=False)
                    
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
        
        # Force horizontal layout with very narrow columns and no gap
        col1, col2, col3, col4 = st.columns([0.8, 0.8, 0.8, 8], gap="small")
        
        with col1:
            st.download_button(
                label="⬇️ Excel",
                data=csv_data,
                file_name="book_club_selections.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col2:
            st.download_button(
                label="📝 Text",
                data=text_data,
                file_name="book_club_selections.txt",
                mime="text/plain",
                use_container_width=True
            )
            
        with col3:
            try:
                pdf_data = generate_pdf_data(book_list_df)
                st.download_button(
                    label="📄 PDF",
                    data=pdf_data,
                    file_name="book_club_selections.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.error("PDF error")
    else:
        st.info("No books in your selection list yet. Search and add some books!")
        if st.button("Back to Search"):
            st.session_state.show_full_list = False
            st.rerun()
