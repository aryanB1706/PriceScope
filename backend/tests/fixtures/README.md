# Scraper fixtures

Saved product pages used by the offline parser tests. No test performs a network request.

## Flipkart

Retrieved live on 2026-10-27:

- `flipkart_in_stock_taupe.html`: https://www.flipkart.com/sony-wh-ch520-50-hrs-playtime-dsee-upscale-multipoint-connection-dual-pairing-bluetooth/p/itm29e4c2b8a0883
- `flipkart_in_stock_black.html`: https://www.flipkart.com/sony-wh-ch520-50-hrs-playtime-dsee-upscale-multipoint-connection-dual-pairing-bluetooth-headset/p/itm064cf3dcf3b5c

## Myntra

Retrieved live on 2026-10-27:

- `myntra_in_stock_celio.html`: https://www.myntra.com/tshirts/celio/celio-men-red-cotton-t-shirt/16861588/buy
- `myntra_out_of_stock_tommy.html`: https://www.myntra.com/tshirts/tommy2bhilfiger/tommy-hilfiger-men-white--navy-blue-striped-round-neck-t-shirt/7324599/buy

## Croma

Retrieved live on 2026-10-27 using the scraper's browser User-Agent and `robots.txt` check:

- `croma_in_stock_tcl.html`: https://www.croma.com/tcl-v6c-139-7-cm-55-inch-4k-ultra-hd-led-smart-google-tv-with-google-voice-assistant-2025-model-/p/315756
- `croma_in_stock_samsung.html`: https://www.croma.com/samsung-qn70f-165-1-cm-65-inch-4k-ultra-hd-mini-led-neo-qled-smart-tizen-tv-with-multiple-voice-assistant-2025-model-/p/315357

Raw `curl` requests initially returned an Akamai 403 for Croma. The browser-like `requests.Session` User-Agent configured in `BaseScraper` was accepted. No proxy or captcha bypass was used.

The Croma out-of-stock test mutates the visible stock markers in the saved TCL page; the fixture itself remains the real page.
