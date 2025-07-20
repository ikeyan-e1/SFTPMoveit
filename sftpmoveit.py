import paramiko
import json
import os
import sys
import stat
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from paramiko import RSAKey, DSSKey, ECDSAKey, Ed25519Key
from paramiko.ssh_exception import SSHException

# ログ設定
def setup_logger(log_path="transfer.log"):
    logger = logging.getLogger("SFTPMoveit")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_path, maxBytes=1 * 1024 * 1024, backupCount=5, encoding='utf-8')
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

# 鍵の自動読み込み（といっても、paramikoで読めるやつを総当たり）
def load_private_key_auto(path, password=None):
    for KeyClass in [RSAKey, DSSKey, ECDSAKey, Ed25519Key]:
        try:
            return KeyClass.from_private_key_file(path, password)
        except SSHException:
            continue
    raise SSHException(f"鍵ファイル形式が不明または読み込めません: {path}")

# 設定の読み込み
def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

# SFTP接続
def connect_sftp(config, logger):
    transport = paramiko.Transport((config["host"], config["port"]))

    if "keyfile" in config and os.path.exists(config["keyfile"]):
        try:
            key = load_private_key_auto(config["keyfile"])
            transport.connect(username=config["username"], pkey=key)
            logger.info(f"鍵認証成功: {config['username']}@{config['host']}")
        except Exception as e:
            logger.error(f"鍵認証失敗 → パスワードへ切り替え: {e}")
            if "password" in config:
                transport.connect(username=config["username"], password=config["password"])
                logger.info(f"パスワード認証成功（鍵失敗後）: {config['username']}@{config['host']}")
            else:
                raise e
    elif "password" in config:
        transport.connect(username=config["username"], password=config["password"])
        logger.info(f"パスワード認証成功: {config['username']}@{config['host']}")
    else:
        raise ValueError("鍵ファイルもパスワードも指定されていません")

    return paramiko.SFTPClient.from_transport(transport)


# リモート先でのディレクトリ階層表現用
def ensure_remote_dirs(sftp, remote_path, logger):
    parts = remote_path.strip("/").split("/")
    current = ""
    for part in parts[:-1]:
        current += "/" + part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            try:
                sftp.mkdir(current)
                logger.info(f"mkdir: {current}")
            except Exception as e:
                logger.warning(f"mkdir失敗: {current} → {e}")



# アップロード処理
def upload_files(sftp, local_dir, remote_dir, logger):
    for root, _, files in os.walk(local_dir):
        for file in files:
            local_path = os.path.join(root, file)
            rel_path = os.path.relpath(local_path, local_dir).replace("\\", "/")
            remote_path = f"{remote_dir}/{rel_path}"
            try:
                ensure_remote_dirs(sftp, remote_path, logger)
                sftp.put(local_path, remote_path)
                logger.info(f"UPLOADED: {local_path} → {remote_path}")
            except Exception as e:
                logger.error(f"アップロード失敗: {local_path} → {e}")


# ダウンロード処理
def download_files(sftp, remote_dir, local_dir, logger):
    def recurse(remote_path, local_path):
        for entry in sftp.listdir_attr(remote_path):
            r_path = f"{remote_path}/{entry.filename}"
            l_path = os.path.join(local_path, entry.filename)

            if stat.S_ISDIR(entry.st_mode):
                os.makedirs(l_path, exist_ok=True)
                recurse(r_path, l_path)
            else:
                try:
                    sftp.get(r_path, l_path)
                    logger.info(f"DOWNLOADED: {r_path} → {l_path}")
                except Exception as e:
                    logger.error(f"ダウンロード失敗: {r_path} → {e}")

    os.makedirs(local_dir, exist_ok=True)
    recurse(remote_dir, local_dir)

def get_config_path():
    script_dir = Path(__file__).resolve().parent
    return script_dir / "config.json"

def get_config_path():
    return Path(sys.executable).parent / "config.json"

def create_config_template(path):
    template = {
        "host": "sftp.example.com",
        "port": 22,
        "username": "your_username",
        "keyfile": "id_rsa",
        "password": "",
        "direction": "upload",  # または "download"
        "local": "C:/YourLocalFolder/",
        "remote": "/remote/folder/path/"
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2)
    print(f"[INFO] config.json が見つからなかったため、テンプレートを生成しました → {path}")

# メイン
def main():
    log_path = Path(sys.executable).parent / "transfer.log"
    logger = setup_logger()
    try:
        config_path = get_config_path()
        if not config_path.exists():
            create_config_template(config_path)
            print("[INFO] テンプレートを編集して再実行してください。")
            sys.exit(1)
        
        config = load_config(config_path)
        logger.info(f"設定ファイル読み込み成功: config.json")

        sftp = connect_sftp(config, logger)

        if config["direction"] == "upload":
            upload_files(sftp, config["local"], config["remote"], logger)
        elif config["direction"] == "download":
            download_files(sftp, config["remote"], config["local"], logger)
        else:
            logger.error(f"direction指定が不正: {config['direction']}")
            logger.info("Invalid direction: should be 'upload' or 'download'.")

        sftp.close()
        logger.info("SFTPセッションを終了しました")
    except Exception as e:
        logger.critical(f"致命的エラー: {e}", exc_info=True)



if __name__ == "__main__":
    main()