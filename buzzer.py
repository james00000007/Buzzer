from click import (
    argument,
    command,
    help_option,
    option,
)
from http.cookiejar import MozillaCookieJar
from io import BytesIO
from os import listdir, path as ospath
from pycurl import (
    Curl,
    FOLLOWLOCATION,
    HEADERFUNCTION,
    HTTPHEADER,
    INFILESIZE,
    NOPROGRESS,
    PUT,
    READDATA,
    UPLOAD,
    URL,
    XFERINFOFUNCTION,
)
from re import search
from requests import Session
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, TaskID
from rich.style import Style
from sys import exit
from traceback import print_exc
from typing import Optional


class BH:
    def __init__(self, cookies: str) -> None:
        self.cookies: MozillaCookieJar = MozillaCookieJar(filename=cookies)
        self.cookies.load(
            ignore_discard=True,
            ignore_expires=True,
        )

        self.progress = Progress()
        self.task: Optional[TaskID] = None
        self.uploaded: Optional[int] = 0
        self.processed: Optional[int] = 0

        self.session: Session = Session()
        self.session.cookies.update(other=self.cookies)
        self.session.cookies.update(self.session.cookies.get_dict())

        self.size: int = 5 * 1024 * 1024 * 1024

        self.token: str = "; ".join(
            [f"{cookie.name}={cookie.value}" for cookie in self.cookies]
        )

        self.BUZZHEAVIER_BASE_URL: str = "https://buzzheavier.com"
        self.BUZZHEAVIER_UPLOAD_URL: Optional[str] = None

    def create_folder(self, name: str) -> str:
        req = self.session.post(
            url=f"{self.BUZZHEAVIER_BASE_URL}/d/",
            headers={
                "hx-current-url": f"{self.BUZZHEAVIER_BASE_URL}/d/",
                "hx-request": "true",
                "hx-target": "tbody",
                "hx-trigger": "create-directory-btn",
            },
            files={
                "name": (None, name),
            },
        )

        data = req.text

        folder = search(
            pattern=r"(?P<id>[a-z0-9]{12})",
            string=data,
        )

        if folder:
            return folder.group("id")

        return data

    def get_complete(self, ids: str, folder: str, complete: list) -> str:
        req = self.session.post(
            url=f"{self.BUZZHEAVIER_BASE_URL}/f/{ids}",
            params={
                "directoryId": folder,
            },
            json={
                "directoryId": folder,
                "parts": complete,
            },
        )

        data = req.json()

        return f"{self.BUZZHEAVIER_BASE_URL}/{data['id']}"

    def get_progress(self, _, __, ___, uploaded: int) -> None:
        last_uploaded = uploaded - self.uploaded
        self.uploaded = uploaded

        if last_uploaded > 0:
            self.processed += last_uploaded
            self.progress.update(
                task_id=self.task,
                completed=self.processed,
            )

    def get_server(self, name: str, size: int) -> tuple:
        req = self.session.post(
            url=f"{self.BUZZHEAVIER_BASE_URL}/f/",
            json={
                "name": name,
                "size": size,
            },
        )

        data = req.json()

        return data["uploadId"], data["uploadUrls"]

    def upload(self, file: str, url: str, number: int, start: int, end: int) -> dict:
        result = BytesIO()

        with open(file=file, mode="rb") as file:
            file.seek(start)

            curl = Curl()
            curl.setopt(
                URL,
                url,
            )
            curl.setopt(PUT, 1)
            curl.setopt(UPLOAD, 1)
            curl.setopt(READDATA, file)
            curl.setopt(INFILESIZE, (end - start))
            curl.setopt(
                HTTPHEADER,
                [
                    f"Content-Length: {end - start}",
                    f"Cookie: {self.token}",
                ],
            )
            curl.setopt(FOLLOWLOCATION, True)
            curl.setopt(NOPROGRESS, False)
            curl.setopt(HEADERFUNCTION, result.write)
            curl.setopt(XFERINFOFUNCTION, self.get_progress)
            curl.perform()
            curl.close()

        data = result.getvalue().decode("UTF-8")

        for line in data.split("\r\n"):
            if line.lower().startswith("etag:"):
                etag = line.split(":", 1)[1].strip()

        return {
            "ETag": etag,
            "PartNumber": number,
        }


@command(
    name="Buzzer (Buzzheavier Uploader)",
    short_help="A Simple Python Script for Uploading File / Folder to Buzzheavier.",
)
@argument(
    "path",
    type=str,
    required=True,
)
@option(
    "--cookies",
    type=str,
    required=False,
    default="buzzer.txt",
    help="Cookies File Path.",
)
@option(
    "--folder",
    type=str,
    required=False,
    # default="GVHguWeq8AA",
    help="Folder ID.",
)
@help_option("--help")
def Buzzheavier(
    path: str,
    cookies: str,
    folder: str,
) -> None:
    LOGGER = Console()

    try:
        if ospath.isdir(path):
            folder = BH(cookies=cookies).create_folder(name=ospath.basename(path))

            if "Folder with same name already exist" in folder:
                LOGGER.print(
                    "Folder Name already exist! Please input Folder ID manually.",
                    style=Style(color="red", bold=True),
                )
                folder = input("Folder ID : ")

            for file in sorted(listdir(path=path)):
                file = ospath.join(path, file)

                if ospath.isdir(file):
                    LOGGER.print(
                        "Buzzheavier does not support Multi Folder yet! Skipping.",
                        style=Style(color="red", bold=True),
                    )
                    continue

                bh = BH(cookies=cookies)
                size = ospath.getsize(file)
                complete = list()

                ids, urls = bh.get_server(name=ospath.basename(file), size=size)

                with bh.progress:
                    bh.task = bh.progress.add_task(
                        description=f"{ospath.basename(file)}",
                        total=size,
                    )

                    with open(file=file, mode="rb"):
                        for i in range((size + bh.size - 1) // bh.size):
                            start = i * bh.size
                            end = min((i + 1) * bh.size, size)

                            part = bh.upload(
                                file=file,
                                url=urls[i],
                                number=(i + 1),
                                start=start,
                                end=end,
                            )

                            complete.append(part)

                bh.get_complete(ids=ids, folder=folder, complete=complete)

            link = f"{bh.BUZZHEAVIER_BASE_URL}/d/{folder}"

        else:
            if folder is None:
                LOGGER.print(
                    "Folder ID not Found! Please input Folder ID manually.",
                    style=Style(color="red", bold=True),
                )
                folder = input("Folder ID : ")

            bh = BH(cookies=cookies)
            size = ospath.getsize(path)
            complete = list()

            ids, urls = bh.get_server(name=ospath.basename(path), size=size)

            with bh.progress:
                bh.task = bh.progress.add_task(
                    description=f"{ospath.basename(path)}",
                    total=size,
                )

                with open(file=path, mode="rb"):
                    for i in range((size + bh.size - 1) // bh.size):
                        start = i * bh.size
                        end = min((i + 1) * bh.size, size)

                        part = bh.upload(
                            file=path,
                            url=urls[i],
                            number=(i + 1),
                            start=start,
                            end=end,
                        )

                        complete.append(part)

            link = bh.get_complete(ids=ids, folder=folder, complete=complete)

    except Exception:
        print_exc()
        exit()

    LOGGER.print("")
    LOGGER.print(
        Panel(
            renderable=(
                f"""
File ID     : {link.split('/')[-1]}
File Name   : {ospath.basename(path)}
File Link   : {link}
"""
            ),
            expand=False,
            style=Style(color="yellow", bold=True),
            border_style=Style(color="green", bold=True),
            padding=(0, 2),
        ),
    )


if __name__ == "__main__":
    print(r"""

        /$$$$$$$                                                   
        | $$__  $$                                                  
        | $$  \ $$ /$$   /$$ /$$$$$$$$ /$$$$$$$$  /$$$$$$   /$$$$$$ 
        | $$$$$$$ | $$  | $$|____ /$$/|____ /$$/ /$$__  $$ /$$__  $$
        | $$__  $$| $$  | $$   /$$$$/    /$$$$/ | $$$$$$$$| $$  \__/
        | $$  \ $$| $$  | $$  /$$__/    /$$__/  | $$_____/| $$      
        | $$$$$$$/|  $$$$$$/ /$$$$$$$$ /$$$$$$$$|  $$$$$$$| $$      
        |_______/  \______/ |________/|________/ \_______/|__/      

                https://github.com/arakurumi/Buzzer

""")
    Buzzheavier()
