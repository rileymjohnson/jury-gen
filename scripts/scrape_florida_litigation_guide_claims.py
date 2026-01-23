import argparse
from itertools import groupby
import json
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup, NavigableString
import requests

DEFAULT_URL = 'https://floridalitigationguide.com/table-of-contents/'
DEFAULT_USERNAME = 'liz@perseediting.com'
DEFAULT_PASSWORD = 'earthairfirewater2024!'

def create_authenticated_session(username: str, password: str) -> requests.Session:
    session = requests.Session()
    login_url = "https://floridalitigationguide.com/login/"
    session.get(login_url)
    payload = {
        "log": username,
        "pwd": password,
        "rememberme": "forever",
        "redirect_to": "https://floridalitigationguide.com/",
        "wp-submit": "Log In"
    }
    session.post("https://floridalitigationguide.com/wp-login.php", data=payload)
    return session

def clean_url(url):
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if 'scholar.google.com' in parsed.netloc and 'case' in params:
        clean_query = urlencode({'case': params['case'][0]})
        return urlunparse(parsed._replace(query=clean_query))
    return url

def prepare_soup(html, preserve_tags=()):
    """Parse HTML, unwrap empty-attr tags (except preserve_tags), merge adjacent <a> tags, convert <a> to markdown."""
    soup = BeautifulSoup(html, 'html.parser')

    for tag in list(soup.find_all()):
        if not tag.attrs and tag.name not in preserve_tags:
            tag.unwrap()

    for a in list(soup.find_all('a')):
        while a.next_sibling:
            nxt = a.next_sibling
            if isinstance(nxt, NavigableString) and not nxt.strip():
                nxt.extract()
                continue
            if (
                    getattr(nxt, 'name', None) == 'a' and
                    nxt.get('href', '').split('?')[0] == a.get('href', '').split('?')[0]
                ):
                a.append(nxt.get_text())
                nxt.decompose()
            else:
                break

    for a in soup.find_all('a'):
        text = a.get_text().strip()
        href = clean_url(a.get('href', ''))
        a.replace_with(f'[{text}]({href})')

    return soup

def collapse_whitespace(text):
    return re.sub(r'\s+', ' ', text).strip()

def handle_description_html(html):
    soup = prepare_soup(html)
    return collapse_whitespace(soup.get_text())

def handle_references_html(html_list: list[str]) -> str:
    lines = []
    for html in html_list:
        soup = prepare_soup(html, preserve_tags=('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br'))
        for el in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            text = collapse_whitespace(el.get_text())
            if not text:
                continue
            if el.name.startswith('h'):
                level = int(el.name[1])
                lines.append(f'{"#" * level} {text}')
            else:
                lines.append(text)
    return '\n\n'.join(lines)

def handle_defenses_html(html_list: list[str]) -> list[str]:
    results = []
    for html in html_list:
        soup = prepare_soup(html, preserve_tags=('p', 'br'))
        text = collapse_whitespace(soup.get_text())
        text = re.sub(r'^\(\d+\)\s*', '', text)
        if text:
            results.append(text)
    return results

def scrape_claims(base_url, username, password):
    session = create_authenticated_session(username, password)
    soup = BeautifulSoup(session.get(base_url).text, 'html.parser')
    claims_table_of_contents = soup.select_one('.table-of-contents')

    claims = []
    for a_tag in claims_table_of_contents.select('div.column > p > a'):
        claim_soup = BeautifulSoup(session.get(a_tag['href']).text, 'html.parser')
        content = claim_soup.select_one('#cs-content')
        title = content.select_one(
            '.x-section > .x-row > .x-row-inner > .x-col > .x-text > .x-text-content > .x-text-content-text > h1'
        ).get_text(strip=True)
        elements = [li.get_text(strip=True) for li in content.select('ol')[-1].select('li')]
        main_content = content.select_one('.x-section > .x-row > .x-row-inner > .x-col').select('.x-text')[2]

        child_elements = [c for c in main_content.children if c.name]
        description_tags, references_tags, defenses_tags = (
            list(g) for k, g in groupby(child_elements, key=lambda e: e.name == 'hr') if not k
        )

        *_, description_tag = description_tags
        description = handle_description_html(str(description_tag))
        references = handle_references_html([str(t) for t in references_tags])
        defenses = handle_defenses_html([str(t) for t in defenses_tags[1:]])
        claims.append({
            'title': title,
            'description': description,
            'elements': elements,
            'defenses': defenses,
            'references': references
        })

    return claims

def main():
    parser = argparse.ArgumentParser(description='Scrape Florida Litigation Guide claims')
    parser.add_argument('-o', '--output', required=True, help='Output JSON file path')
    parser.add_argument('-u', '--url', default=DEFAULT_URL, help='Base URL for table of contents')
    parser.add_argument('--username', default=DEFAULT_USERNAME, help='Login username')
    parser.add_argument('--password', default=DEFAULT_PASSWORD, help='Login password')

    args = parser.parse_args()

    claims = scrape_claims(args.url, args.username, args.password)

    with open(args.output, 'w') as f:
        json.dump(claims, f, indent=2)

if __name__ == '__main__':
    main()
