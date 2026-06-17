import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def handle_popups_and_overlays(page: Page):
    """
    Hide common popups and cookie banners using an aggressive non-destructive stealth approach.
    """
    try:
        try:
            page.wait_for_function("""
                 () => {
                     const skeletons = document.querySelectorAll('[class*="skeleton"], [class*="loading-shimmer"], .shimmer');
                     return skeletons.length === 0;
                 }
            """, timeout=500)
        except: pass 

        page.evaluate("""
            () => {
                const isFixedOrHighZIndex = (el) => {
                    let current = el;
                    while (current && current !== document.body && current !== document.documentElement) {
                        const style = window.getComputedStyle(current);
                        if (style.position === 'fixed' || style.position === 'absolute' || parseInt(style.zIndex) > 5) {
                            return true;
                        }
                        current = current.parentElement;
                    }
                    return false;
                };

                const buttons = Array.from(document.querySelectorAll('button, a, span, [role="button"]'));
                const acceptKeywords = [
                    'accept all', 'allow all', 'accept cookies', 'agree', 'got it', 
                    'accept and close', 'confirm', 'allow cookies', 'agree & closed',
                    'reject non-essential', 'reject all', 'reject non essential', 'decline'
                ];
                
                for (const btn of buttons) {
                    const text = btn.innerText ? btn.innerText.toLowerCase().trim() : '';
                    if (acceptKeywords.some(kw => text === kw || text.includes(kw))) {
                        if (isFixedOrHighZIndex(btn)) {
                            try { btn.click(); } catch(e) {}
                        }
                    }
                }
            }
        """)
        page.wait_for_timeout(50)

        page.evaluate("""
            () => {
                const selectorsToHide = [
                    '#onetrust-banner-sdk', '.ot-sdk-container', '#didomi-notice', 
                    '#cookie-banner', '.cookie-banner', '[id*="cookie"]', '[class*="cookie"]',
                    '[class*="consent"]', '[id*="consent"]', '[class*="privacy"]',
                    '.modal-backdrop', '.modal-open', '.fade.in',
                    '.bx-row-submit-button', '#newsletter-popup', '[id*="newsletter"]',
                    '[id^="sp_message_container"]', '.sp_veil', '.evidon-banner',
                    '#consent-banner', '.gdpr-consent', '.overlay', '.fixed-overlay',
                    '[class*="NewsletterPopup"]', '[class*="PromotionPopup"]',
                    '[id*="pop-up"]', '[class*="pop-up"]', '[id*="modal"]',
                    '[class*="cookie-consent"]', '[id*="cookie-consent"]',
                    '[class*="cookiebanner"]', '[id*="cookiebanner"]'
                ];
                
                const totalElementsCount = document.getElementsByTagName('*').length;
                const totalTextLength = document.body ? document.body.innerText.length : 0;

                const isMajorLayout = (el) => {
                    if (!el) return false;
                    
                    const tagName = el.tagName;
                    // Never hide structural HTML/semantic containers
                    if (['BODY', 'HTML', 'HEADER', 'NAV', 'MAIN', 'ARTICLE', 'SECTION', 'FOOTER'].includes(tagName)) {
                        return true;
                    }
                    
                    const id = (el.id || '').toLowerCase();
                    const commonIds = [
                        'app', 'root', 'main-content', 'header', 'nav', 'main', 'content', 
                        'a-page', 'wrapper', 'page-wrapper', 'content-wrapper', 'site-container', 
                        'container', '__next', '__layout'
                    ];
                    if (commonIds.includes(id)) {
                        return true;
                    }
                    
                    // Safety threshold: count of child elements & text length
                    const childElements = el.getElementsByTagName('*').length;
                    if (childElements > totalElementsCount * 0.25) {
                        return true;
                    }
                    
                    const elText = el.innerText ? el.innerText.length : 0;
                    if (totalTextLength > 0 && elText > totalTextLength * 0.25) {
                        return true;
                    }
                    
                    return false;
                };
                
                selectorsToHide.forEach(s => {
                    document.querySelectorAll(s).forEach(el => {
                        if (isMajorLayout(el)) {
                            console.log("GCRAWL_SKIPPED: Major layout skipped: selector=" + s + ", tag=" + el.tagName + ", id=" + el.id + ", class=" + el.className);
                            return;
                        }
                        el.style.setProperty('display', 'none', 'important');
                        el.setAttribute('data-gcrawl-hidden', 'true');
                        console.log("GCRAWL_HIDDEN: Hidden selector=" + s + ", tag=" + el.tagName + ", id=" + el.id + ", class=" + el.className);
                    });
                });
                
                document.body.style.setProperty('overflow', 'auto', 'important');
                document.documentElement.style.setProperty('overflow', 'auto', 'important');
                
                const potentialOverlays = document.querySelectorAll('body > *, [class*="modal"], [class*="popup"], [class*="overlay"], [class*="dialog"], [id*="modal"], [id*="popup"]');
                potentialOverlays.forEach(el => {
                    if (isMajorLayout(el)) {
                        console.log("GCRAWL_SKIPPED: Major layout skipped: potentialOverlay, tag=" + el.tagName + ", id=" + el.id + ", class=" + el.className);
                        return;
                    }

                    const style = window.getComputedStyle(el);
                    const isFixedOrAbsolute = style.position === 'fixed' || style.position === 'absolute';
                    const hasHighZ = parseInt(style.zIndex) > 5;
                    
                    if (isFixedOrAbsolute || hasHighZ) {
                        const idOrClass = ((el.id || '') + ' ' + (el.className || '')).toLowerCase();
                        const isBannerOrPopup = idOrClass.includes('cookie') || idOrClass.includes('consent') || 
                                                 idOrClass.includes('privacy') || idOrClass.includes('gdpr') || 
                                                 idOrClass.includes('banner') || idOrClass.includes('popup') || 
                                                 idOrClass.includes('modal') || idOrClass.includes('overlay') ||
                                                 idOrClass.includes('dialog') || el.parentElement === document.body;
                        
                        if (isBannerOrPopup) {
                            const text = el.innerText ? el.innerText.toLowerCase() : '';
                            if (text.includes('cookie') || text.includes('consent') || text.includes('privacy') || text.includes('gdpr') || text.includes('we use cookies')) {
                                el.style.setProperty('display', 'none', 'important');
                                el.setAttribute('data-gcrawl-hidden', 'true');
                                console.log("GCRAWL_HIDDEN: Hidden potentialOverlay, tag=" + el.tagName + ", id=" + el.id + ", class=" + el.className);
                            }
                        }
                    }
                });
            }
        """)
        page.wait_for_timeout(50)
        
    except Exception as e:
        logger.debug(f"Popup handling failed: {e}")
