import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def handle_popups_and_overlays(page: Page):
    """
    Hide common popups and cookie banners using an aggressive non-destructive CSS injection and JS scanner.
    Unlocks HTML/body scrolling if popups have locked scroll behavior.
    Executes across the main page and all child frames (iframes), piercing Shadow DOM boundaries safely.
    """
    js_code = """
        () => {
            // 1. Inject generic styling overrides
            if (!document.getElementById('gcrawl-stealth-popup-hide-styles')) {
                const style = document.createElement('style');
                style.id = 'gcrawl-stealth-popup-hide-styles';
                style.innerHTML = `
                    /* Force screen scrollability in case cookie modals locked the page */
                    html, body {
                        overflow: auto !important;
                        overflow-y: auto !important;
                    }
                    
                    /* Hide common consent containers */
                    #onetrust-consent-sdk, 
                    #qc-cmp2-container, 
                    #usercentrics-root, 
                    #didomi-popup, 
                    .didomi-popup-container, 
                    #sp-consent-notice,
                    #cmp-banner,
                    .cc-window, 
                    .cc-banner, 
                    .cc-floating, 
                    .cc-overlay,
                    .cookie-notice,
                    #cookie-notice,
                    .cookie-banner,
                    #cookie-banner,
                    .consent-banner,
                    #consent-banner,
                    .cookies-banner,
                    #cookies-banner,
                    #cookieconsent,
                    .cookieconsent,
                    .cookie-consent,
                    #cookie-consent,
                    .cookieconsent-container,
                    .cookie-bar,
                    #cookie-bar,
                    #cookiebar,
                    .cookie-popup,
                    #cookie-popup,
                    .privacy-popup,
                    #privacy-popup,
                    .privacy-banner,
                    #privacy-banner,
                    .consent-modal,
                    #consent-modal,
                    [class*="cookie-banner" i],
                    [id*="cookie-banner" i],
                    [class*="cookie-consent" i],
                    [id*="cookie-consent" i],
                    [class*="cookieconsent" i],
                    [id*="cookieconsent" i],
                    [class*="consent-banner" i],
                    [id*="consent-banner" i] {
                        display: none !important;
                        visibility: hidden !important;
                        opacity: 0 !important;
                        pointer-events: none !important;
                        height: 0 !important;
                        min-height: 0 !important;
                        overflow: hidden !important;
                    }
                `;
                document.head.appendChild(style);
            }
            
            // 2. Helper to hide elements aggressively
            const hideElement = (el) => {
                if (!el || el.nodeType !== 1) return;
                
                // SAFETY CHECK: Never hide the root container or elements with massive amounts of text
                if (el === document.body || el === document.documentElement) return;
                const id = (el.id || '').toLowerCase();
                if (id === 'app' || id === 'root' || id === '__next') return;
                const text = el.textContent || '';
                if (text.length > 500) return; 
                
                el.style.setProperty('display', 'none', 'important');
                el.style.setProperty('visibility', 'hidden', 'important');
                el.style.setProperty('opacity', '0', 'important');
                el.style.setProperty('pointer-events', 'none', 'important');
                el.style.setProperty('height', '0', 'important');
                el.style.setProperty('min-height', '0', 'important');
                el.style.setProperty('overflow', 'hidden', 'important');
            };

            // 3. Scan for custom/obfuscated cookie modals based on general keywords
            const keywords = ["cookie", "cookies", "consent", "gdpr", "cookie-policy", "cookie-settings", "terms of service", "accept cookies"];
            const containsCookieKeyword = (text) => {
                if (!text) return false;
                if (text.length > 500) return false; // Safety: Cookie popups are not entire pages
                const lowercaseText = text.toLowerCase();
                return keywords.some(keyword => lowercaseText.includes(keyword));
            };

            // Helper to get parent traversing shadow DOM boundary
            const getParent = (el) => {
                if (!el) return null;
                if (el.parentNode && el.parentNode.host) {
                    return el.parentNode.host;
                }
                return el.parentElement || el.parentNode;
            };

            // 4. Targeted button/consent action search (multilingual support)
            const consentButtonKeywords = [
                "allow all cookies", "accept all cookies", "decline optional", 
                "only allow essential", "decline cookies", "accept cookies", 
                "allow cookies", "accept optional", "cookies allow", "allow selection",
                "accept selection", "agree to cookies", "cookie settings",
                "alle cookies erlauben", "cookies akzeptieren", "nur essenzielle",
                "accepter tous", "accepter les cookies", "aceptar todas", "aceptar cookies",
                "accetta tutti", "accetta i cookie", "allow the use of cookies",
                "allow all", "decline all"
            ];

            const findConsentButtons = (root) => {
                const found = [];
                const walk = (node) => {
                    if (!node) return;
                    if (node.nodeType === 1 && node.tagName) {
                        const tagName = node.tagName.toLowerCase();
                        if (['button', 'a', 'span', 'div'].includes(tagName) || node.getAttribute('role') === 'button') {
                            const text = node.textContent ? node.textContent.trim().toLowerCase() : '';
                            if (text && consentButtonKeywords.some(keyword => text === keyword || text.includes(keyword))) {
                                found.push(node);
                            }
                        }
                    }
                    if (node.children) {
                        Array.from(node.children).forEach(walk);
                    }
                    if (node.shadowRoot) {
                        walk(node.shadowRoot);
                    }
                };
                walk(root);
                return found;
            };

            // Hide containing overlays based on matched consent buttons
            try {
                const consentButtons = findConsentButtons(document);
                consentButtons.forEach(el => {
                    try {
                        let container = el;
                        let parent = getParent(el);
                        while (parent && parent !== document.body && parent !== document) {
                            if (parent.nodeType === 1) {
                                const style = window.getComputedStyle(parent);
                                const isContainer = style.position === 'fixed' || style.position === 'absolute' || parseInt(style.zIndex) > 5;
                                if (isContainer) {
                                    container = parent;
                                    break;
                                }
                            }
                            parent = getParent(parent);
                        }
                        hideElement(container);
                    } catch (e) {}
                });
            } catch (e) {}

            // Fallback: Scan direct body children
            try {
                Array.from(document.body.children).forEach(el => {
                    try {
                        if (el.nodeType === 1) {
                            const style = window.getComputedStyle(el);
                            const isOverlay = style.position === 'fixed' || style.position === 'absolute' || parseInt(style.zIndex) > 99;
                            if (isOverlay && containsCookieKeyword(el.textContent)) {
                                hideElement(el);
                            }
                        }
                    } catch (e) {}
                });
            } catch (e) {}

            // Fallback: Scan dialog/modal roles (Meta sites use dialog/presentation roles for consent popups)
            try {
                const dialogs = document.querySelectorAll('div[role="dialog"], div[role="presentation"], div[class*="modal" i], div[id*="modal" i]');
                dialogs.forEach(el => {
                    try {
                        if (el.nodeType === 1 && containsCookieKeyword(el.textContent)) {
                            let container = el;
                            let parent = getParent(el);
                            while (parent && parent !== document.body && parent !== document) {
                                if (parent.nodeType === 1) {
                                    const style = window.getComputedStyle(parent);
                                    const isContainer = style.position === 'fixed' || style.position === 'absolute' || parseInt(style.zIndex) > 5;
                                    if (isContainer) {
                                        container = parent;
                                        break;
                                    }
                                }
                                parent = getParent(parent);
                            }
                            hideElement(container);
                        }
                    } catch (e) {}
                });
            } catch (e) {}

            // 5. Close login modals / sign-up popups (e.g. Flipkart, etc.)
            try {
                const closeSelectors = [
                    'button._2KpZ6l._2doB4z',
                    'span._30XB9F',
                    'button[class*="close" i]',
                    '[class*="close-button" i]',
                    '[class*="modal-close" i]',
                    '[aria-label*="close" i]',
                    'button[aria-label*="close" i]'
                ];
                for (const sel of closeSelectors) {
                    const btns = document.querySelectorAll(sel);
                    btns.forEach(btn => {
                        if (btn && typeof btn.click === 'function') {
                            // Skip OneTrust/cookie consent close buttons to prevent page reload/scroll collapse
                            const id = (btn.id || '').toLowerCase();
                            const cls = (btn.className || '').toLowerCase();
                            if (id.includes('onetrust') || id.includes('ot-') || cls.includes('onetrust') || cls.includes('ot-')) {
                                return;
                            }
                            btn.click();
                        }
                    });
                }
            } catch (e) {}
        }
    """
    try:
        # Run inside main frame
        page.evaluate(js_code)
        
        # Run inside same-origin child frames (iframes) to prevent Playwright context evaluation hangs on blocked/cross-origin frames
        from urllib.parse import urlparse
        try:
            main_domain = urlparse(page.url).netloc.lower()
        except:
            main_domain = ""

        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                if frame.is_detached():
                    continue
                frame_url = frame.url
                if not frame_url or frame_url == "about:blank":
                    continue
                frame_domain = urlparse(frame_url).netloc.lower()
                if frame_domain != main_domain:
                    # Skip cross-origin child frames as they can block page evaluation indefinitely
                    continue
                
                frame.evaluate(js_code)
            except:
                pass
        logger.info("Successfully ran CSS and JS scanner to hide cookie banners and unlock scrolling across all frames.")
    except Exception as e:
        logger.debug(f"Failed to handle popups and overlays: {e}")
