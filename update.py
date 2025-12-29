import io
import json
import os
import re
import zipfile
from typing import Dict, List, Union

import demjson3  # type: ignore
import requests
from bs4 import BeautifulSoup, Tag
from google_play_scraper import app  # type: ignore

LimojiItemType = Dict[str, Union[int, str, List[List[str]]]]
LimojiType = Dict[str, List[LimojiItemType]]
LimojiSortedType = Dict[str, LimojiItemType]
MainJsDictType = Dict[str, Dict[str, Dict[str, str]]]

DOWNLOAD_INTERVAL = 1


def search_bracket(text: str):
    depth = 0
    is_str = False

    for count, char in enumerate(text):
        if char == '"':
            is_str = not is_str

        if is_str == False:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1

        if depth == 0:
            return count


def gif2png(path: str) -> str:
    return path.replace(".gif", ".png").replace("faces", "faces_png")


def get_main_js_url() -> str:
    page = requests.get("https://lihkg.com")
    soup = BeautifulSoup(page.text, "html.parser")
    src_tag = soup.find(src=re.compile("main.js"))
    assert isinstance(src_tag, Tag)
    main_js_url = src_tag.get("src")
    assert isinstance(main_js_url, str)
    return main_js_url


def get_main_js() -> MainJsDictType:
    main_js_url = get_main_js_url()
    r = requests.get(main_js_url).text

    # Find start (Slow but more robust)
    # start_pos = re.search(r'{.*:{icons:{"assets\/faces\/.*\/.*.gif"', r).start()
    # r = r[start_pos:]

    # Find start (Fast but less robust)
    start_pos = r.find('{normal:{icons:{"assets/faces/normal/')
    r = r[start_pos:]

    # Find end
    end_pos = search_bracket(r)
    assert end_pos is not None
    r = r[: end_pos + 1]

    # ! symbol affects parsing
    r = r.replace("!0", "1")

    # Parse
    data: MainJsDictType = demjson3.decode(r)  # type: ignore
    with open("jsons/main_js.json", "w+", encoding="utf8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    return data  # type: ignore


def get_app_version() -> str:
    result = app("com.lihkg.app")
    return result["version"]


def get_asset(mapping: Dict[str, str]) -> LimojiSortedType:
    version = get_app_version()
    headers = {"User-Agent": f"LIHKG/{version} Android/11 Google/sdk_gphone_x86_64"}

    r = requests.get("https://lihkg.com/api_v2/system/property", headers=headers)
    asset_url = json.loads(r.text)["response"]["asset"]["patch"][0]["url"]

    asset_zip = requests.get(asset_url)
    with zipfile.ZipFile(io.BytesIO(asset_zip.content)) as zf:
        # Some sticker pack (e.g. husky) is present in main_js but not in limoji
        with zf.open("limoji.json") as f, open(
            "jsons/limoji.json", "w+", encoding="utf8"
        ) as g:
            limoji: LimojiType = json.load(f)
            json.dump(limoji, g, indent=4, ensure_ascii=False)

        for i in zf.namelist():
            if i.startswith("assets/faces"):
                os.makedirs(os.path.dirname(i), exist_ok=True)
                zf.extract(i)

    main_js = get_main_js()
    return limoji_sorting(main_js, limoji, mapping)


def limoji_sorting(
    main_js: MainJsDictType, limoji: LimojiType, mapping: Dict[str, str]
) -> LimojiSortedType:
    limoji_sorted: LimojiSortedType = {}
    for pack in main_js:
        icons_list = [
            [code, gif_path, gif2png(gif_path)]
            for gif_path, code in main_js[pack].get("icons", {}).items()
        ]

        special_list = [
            [code, gif_path, gif2png(gif_path)]
            for gif_path, code in main_js[pack].get("special", {}).items()
        ]

        listed_icons_path = [i[1] for i in icons_list]
        listed_icons_path += [i[1] for i in special_list]
        listed_icons_name = [
            os.path.splitext(os.path.split(i)[-1])[0] for i in listed_icons_path
        ]
        pack_dir = os.path.dirname(listed_icons_path[0])

        for i in sorted(os.listdir(pack_dir)):
            f_base = os.path.splitext(i)[0]
            if f_base not in listed_icons_name:
                gif_path = os.path.join(pack_dir, f"{f_base}.gif")
                png_path = gif2png(gif_path)
                special_list.append(["", gif_path, png_path])

        limoji_sorted[pack] = {
            "pack_name": mapping.get(pack, pack),
            "icons": icons_list,
            "special": special_list,  # limoji.json does not have data about special icons
        }

    # "big" pack missing from main_js.json
    limoji_big = [i for i in limoji["emojis"] if i["cat"] == "big"][0]
    limoji_sorted["big"] = {
        "pack_name": mapping.get("big", "big"),
        "icons": limoji_big.get("icons", []),
        "special": [],
    }

    with open("jsons/limoji_sorted.json", "w+", encoding="utf8") as f:
        json.dump(limoji_sorted, f, indent=4, ensure_ascii=False)

    return limoji_sorted


def update_readme(limoji: LimojiSortedType):
    with open("README_TEMPLATE") as f:
        readme = f.read()

    body = "| Code | Name | Preview | View |\n"
    body += "| --- | --- | --- | --- |\n"
    body += f"| (All) | N/A | N/A | [View](./view/all.md) |\n"

    for pack, v in limoji.items():
        pack_name = v["pack_name"]
        icons = v["icons"]
        assert isinstance(icons, list)
        preview_path = icons[0][1]
        preview_name = os.path.split(preview_path)[-1]

        body += f"| {pack} | {pack_name} | ![{preview_name}]({preview_path}) | [View](./view/{pack}.md) |\n"

    readme = readme.replace("{body}", body)

    with open("README.md", "w+") as f:
        f.write(readme)


def update_view(limoji: LimojiSortedType):
    with open("view/all.md", "w+") as f:
        f.write("# All icons\n")

        for pack, v in limoji.items():
            pack_name = v["pack_name"]
            body = f"## {pack} [{pack_name}]\n"

            body += "| Filename | Emoji | GIF | PNG |\n"
            body += "| --- | --- | --- | --- |\n"

            for i in ("icons", "special"):
                pack_info = v.get(i, [])
                assert isinstance(pack_info, list)
                for emoji, gif_path, png_path in pack_info:
                    fname = os.path.split(gif_path)[-1]
                    name = os.path.splitext(fname)[0]
                    body += f"| {name} | `{emoji}` | ![{name}](../{gif_path}) | ![{name}](../{png_path}) |\n"

            body += "\n"

            with open(f"view/{pack}.md", "w+") as g:
                g.write(body)

            f.write(body)


def main():
    with open("jsons/mapping.json") as f:
        mapping: Dict[str, str] = json.load(f)

    limoji = get_asset(mapping)

    update_readme(limoji)
    update_view(limoji)


if __name__ == "__main__":
    main()
