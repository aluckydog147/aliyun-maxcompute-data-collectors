# Copyright 1999-2019 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import sys
import argparse

from proc_pool import ProcessPool

'''
   [output directory]
   |______Report.html
   |______[database name]
          |______odps_ddl
          |      |______tables
          |      |      |______[table name].sql
          |      |______partitions
          |             |______[table name].sql
          |______hive_udtf_sql
                 |______single_partition
                 |      |______[table name].sql
                 |______multi_partition
                        |______[table name].sql
'''

temp_func_name_multi = "odps_data_dump_multi"
class_name_multi = "com.aliyun.odps.datacarrier.transfer.OdpsDataTransferUDTF"
temp_func_name_single = "odps_data_dump_single"
class_name_single = "com.aliyun.odps.datacarrier.transfer.OdpsPartitionTransferUDTF"
pool = ProcessPool(20, False)


def submit(cmd: str, log_dir: str, retry=5) -> None:
    pool.submit(command=cmd, log_dir=log_dir, retry=retry)


def get_runnable_hive_sql(
        file_path: str,
        udtf_resource_path: str,
        odps_config_path: str,
        extra_settings: str
) -> str:
    with open(file_path) as fd:
        hive_sql = fd.read()
    with open(extra_settings) as fd:
        settings = fd.readlines()

    hive_sql = hive_sql.replace("\n", " ")
    hive_sql = hive_sql.replace("`", "")

    hive_sql_list = []
    hive_sql_list.append("add jar %s;" % udtf_resource_path)
    hive_sql_list.append("add file %s;" % odps_config_path)
    hive_sql_list.append("create temporary function %s as '%s';" % (
        temp_func_name_multi, class_name_multi))
    hive_sql_list.append("create temporary function %s as '%s';" % (
        temp_func_name_single, class_name_single))
    for setting in settings:
        if not setting.startswith("#") and len(setting.strip()) != 0:
            hive_sql_list.append("set %s;" % setting)
    hive_sql_list.append(hive_sql)

    return " ".join(hive_sql_list)


def run_all(
        root: str,
        udtf_resource_path: str,
        odps_config_path: str,
        hive_sql_log_root: str,
        extra_settings: str,
) -> None:
    databases = os.listdir(root)
    for database in databases:
        if database == "report.html":
            continue
        hive_multi_partition_sql_dir = os.path.join(
            root, database, "hive_udtf_sql", "multi_partition")
        hive_multi_partition_sql_files = os.listdir(
            hive_multi_partition_sql_dir)
        for hive_multi_partition_sql_file in hive_multi_partition_sql_files:
            file_path = os.path.join(
                hive_multi_partition_sql_dir, hive_multi_partition_sql_file)
            hive_multi_partition_sql = get_runnable_hive_sql(
                file_path, udtf_resource_path, odps_config_path, extra_settings)

            table = hive_multi_partition_sql_file[: -4]
            hive_sql_log_dir = os.path.join(hive_sql_log_root, database, table)
            os.makedirs(hive_sql_log_dir, exist_ok=True)

            command = "hive -e \"%s\"" % hive_multi_partition_sql
            submit(command, log_dir=hive_sql_log_dir)


def run_single_file(
        hive_single_partition_sql_path: str,
        udtf_resource_path: str,
        odps_config_path: str,
        hive_sql_log_root: str,
        extra_settings: str) -> None:

    hive_single_partition_sql = get_runnable_hive_sql(
        hive_single_partition_sql_path,
        udtf_resource_path,
        odps_config_path,
        extra_settings)

    hive_sql_log_dir = os.path.join(hive_sql_log_root, hive_single_partition_sql_path[: -4])
    os.makedirs(hive_sql_log_dir, exist_ok=True)

    command = "hive -e \"%s\"" % hive_single_partition_sql
    submit(command, log_dir=hive_sql_log_dir)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run hive UDTF SQL automatically.')
    parser.add_argument(
        "--input_all",
        required=False,
        help="path to directory generated by meta processor")
    parser.add_argument(
        "--input_single_file",
        required=False,
        help="path to a single sql file")
    parser.add_argument(
        "--settings",
        required=False,
        help="path to extra settings to set before running a hive sql")
    parser.add_argument(
        "--parallelism",
        required=False,
        help="max parallelism of running hive sql")
    args = parser.parse_args()

    # Get path to udtf jar & odps config
    script_path = os.path.dirname(os.path.realpath(__file__))
    odps_data_carrier_path = os.path.dirname(script_path)
    odps_config_path = os.path.join(
        odps_data_carrier_path, "odps_config.ini")
    extra_settings_path = os.path.join(
        odps_data_carrier_path, "extra_settings.ini")
    if not os.path.exists(odps_config_path):
        print("ERROR: %s does not exist" % odps_config_path)
        sys.exit(1)

    if args.input_single_file is not None:
        args.input_single_file = os.path.abspath(args.input_single_file)
    if args.input_all is not None:
        args.input_all = os.path.abspath(args.input_all)
    if args.settings is None:
        args.settings = extra_settings_path
    if args.parallelism is None:
        args.parallelism = 1

    os.chdir(odps_data_carrier_path)

    udtf_path = os.path.join(
        odps_data_carrier_path,
        "libs",
        "data-transfer-hive-udtf-1.0-SNAPSHOT-jar-with-dependencies.jar")
    hive_sql_log_root = os.path.join(
        odps_data_carrier_path,
        "log",
        "hive_sql")

    if not os.path.exists(udtf_path):
        print("ERROR: %s does not exist" % udtf_path)
        sys.exit(1)

    pool.start()
    if args.input_single_file is not None:
        run_single_file(args.input_single_file, udtf_path, odps_config_path, hive_sql_log_root,
                        args.settings)
    elif args.input_all is not None:
        run_all(args.input_all, udtf_path, odps_config_path, hive_sql_log_root,
                args.settings)
    else:
        print("ERROR: please specify --input_all or --input_single_file")
        sys.exit(1)
    pool.join_all()
    pool.stop()
