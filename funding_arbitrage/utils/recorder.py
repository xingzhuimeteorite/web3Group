import os
import csv
from datetime import datetime

class CsvRecorder:
    def __init__(self, project_root: str, file_name: str, header: list):
        """
        初始化记录器。

        Args:
            project_root (str): 项目的根目录。
            file_name (str): CSV 文件名 (例如: 'opportunities.csv')。
            header (list): CSV 文件的表头。
        """
        log_dir = os.path.join(project_root, 'logs')
        self.file_path = os.path.join(log_dir, file_name)
        self.header = header
        self._ensure_file_and_header()

    def _ensure_file_and_header(self):
        """确保CSV文件所在的目录存在。"""
        directory = os.path.dirname(self.file_path)
        if not os.path.exists(directory):
            os.makedirs(directory)

    def _write_header_if_needed(self):
        """如果文件不存在，则写入表头。"""
        if not os.path.isfile(self.file_path):
            with open(self.file_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.header)

    def record(self, data):
        """
        将一行数据追加到CSV文件中。

        :param data: 一个字典，其键应与初始化时提供的表头匹配。
        """
        with open(self.file_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.header)
            writer.writerow(data)