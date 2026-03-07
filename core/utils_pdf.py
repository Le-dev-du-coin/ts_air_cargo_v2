import os
import asyncio
from django.template.loader import render_to_string
from django.http import HttpResponse
from playwright.async_api import async_playwright


async def generate_pdf_playwright(html_content, format="A4", landscape=False):
    """Génère un PDF à partir d'un contenu HTML en utilisant Playwright."""
    async with async_playwright() as p:
        # Utilise un navigateur déjà installé ou tente de le lancer
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        # Définit le contenu HTML
        # wait_until="networkidle" est crucial pour s'assurer que les polices et images sont chargées
        await page.set_content(html_content, wait_until="networkidle")

        # Génère le PDF
        pdf_bytes = await page.pdf(
            format=format,
            landscape=landscape,
            print_background=True,
            margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
            display_header_footer=False,
            prefer_css_page_size=True,
        )

        await browser.close()
        return pdf_bytes


def render_to_pdf_playwright(
    template_src,
    context_dict,
    request=None,
    format="A4",
    landscape=False,
    filename="document.pdf",
):
    """
    Fonction utilitaire pour rendre un template Django en PDF via Playwright.
    Supporte maintenant le formatage et l'orientation.
    """
    html_content = render_to_string(template_src, context_dict, request=request)

    # Exécute la boucle asynchrone pour Playwright
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # Cas rare en Django synchrone mais possible avec certains serveurs
        import nest_asyncio

        nest_asyncio.apply()

    pdf_bytes = loop.run_until_complete(
        generate_pdf_playwright(html_content, format=format, landscape=landscape)
    )

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
