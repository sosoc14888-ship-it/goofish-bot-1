import asyncio
from goofish import GoofishParser

async def main():
    parser = GoofishParser()

    ads = await parser.search("rick owens")

    print("FOUND:", len(ads))

    for ad in ads[:5]:
        print(ad["title"])
        print(ad["price"])
        print(ad["url"])
        print("----")

asyncio.run(main())
