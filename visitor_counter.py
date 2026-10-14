"""Count anonymous returning browsers using durable server-side storage."""
import hashlib
from uuid import UUID
import requests
import streamlit as st
import streamlit.components.v2 as components

JS = """
export default function(component) {
    const {data, setStateValue} = component;
    let token;
    try {
        const key = 'pool-noord-holland-visitor-v1';
        token = localStorage.getItem(key);
        if (!token || !/^[0-9a-f-]{36}$/i.test(token)) {
            token = crypto.randomUUID();
            localStorage.setItem(key, token);
        }
    } catch (_) {
        token = 'unavailable';
    }
    if (data !== token) setStateValue('token', token);
}
"""
identity_component = components.component('pool_visitor_identity', js=JS)

class VisitorError(Exception):
    pass


def register_visitor(token, settings):
    try:
        token = str(UUID(token))
    except (ValueError, TypeError, AttributeError):
        raise VisitorError('Invalid browser identity.') from None
    url, key = settings.get('url', '').rstrip('/'), settings.get('secret_key', '')
    if not url.startswith('https://') or not key:
        raise VisitorError('Visitor storage is not connected.')
    digest = hashlib.sha256(('pool-noord-holland-v1:' + token).encode()).hexdigest()
    headers = {'apikey': key, 'Content-Type': 'application/json'}
    if not key.startswith('sb_secret_'):
        headers['Authorization'] = 'Bearer ' + key
    try:
        response = requests.post(url + '/rest/v1/rpc/pool_register_visitor',
            headers=headers, json={'visitor_hash': digest}, timeout=10)
        response.raise_for_status()
        count = response.json()
        if type(count) is not int or count < 1:
            raise ValueError()
        return count
    except (requests.RequestException, ValueError):
        raise VisitorError('Visitor count temporarily unavailable.') from None


def show_visitor_count():
    try:
        settings = st.secrets.get('visitors', st.secrets.get('shared_ignores', {}))
    except FileNotFoundError:
        settings = {}
    if not settings.get('url') or not settings.get('secret_key'):
        return
    previous = st.session_state.get('visitor_token')
    identity = identity_component(key='pool_visitor', data=previous,
        default={'token': None}, on_token_change=lambda: None)
    token = identity.token
    if not token:
        return
    st.session_state.visitor_token = token
    if token == 'unavailable':
        return
    if st.session_state.get('visitor_registered') != token:
        try:
            st.session_state.visitor_count = register_visitor(token, settings)
            st.session_state.visitor_registered = token
        except VisitorError:
            return
    st.caption(f"Unique visitors: {st.session_state.visitor_count:,} · Counted by browser since tracking began")


SCROLL_JS = """
export default function(component) {
    const {data} = component;
    if (!data || !data.target || !data.nonce) return;
    let observer, timer;
    function reveal() {
        const target = document.getElementById(data.target);
        if (!target || target.getClientRects().length === 0) return false;
        if (target.dataset.lastScroll !== data.nonce) {
            target.dataset.lastScroll = data.nonce;
            target.focus({preventScroll:true});
            target.scrollIntoView({block:'start', behavior:
                matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
        }
        if (observer) observer.disconnect();
        if (timer) clearTimeout(timer);
        return true;
    }
    if (!reveal()) {
        observer = new MutationObserver(reveal);
        observer.observe(document.body, {childList:true, subtree:true, attributes:true});
        timer = setTimeout(() => observer.disconnect(), 8000);
    }
    return () => { if (observer) observer.disconnect(); if (timer) clearTimeout(timer); };
}
"""


def scroll_to_results(request):
    scroll_component = components.component('pool_results_scroll', js=SCROLL_JS)
    scroll_component(key='results_scroll', data=request)
