"""生成打包产物的启动说明文件

由 build.bat 在构建后调用。之所以不在 bat 里直接 echo：
cmd.exe 对 UTF-8 中文的解析不可靠（多字节序列中可能含被当作运算符的字节），
会把中文行误判为命令并报 "'...' is not recognized"。
把中文文本生成交给 python，可彻底规避该问题。

用法：
    python generate_launcher_notes.py <version> <output_dir>
"""
import io
import os
import sys

TEMPLATE = """AutoDoor 行为树 {version} - 启动说明
=====================================================

1. 图形界面
   双击 autodoor-behaviortree-{version}.exe

2. 命令行（CLI）
   在本目录打开 CMD，执行：
       autodoor-cli.exe plugin nodes
       autodoor-cli.exe ai validate D:\\auto_projects\\demo\\tree.json
       autodoor-cli.exe run D:\\auto_projects\\demo\\tree.json --headless

   注意：图形界面版 exe 没有标准输出，脚本调用一律用 autodoor-cli.exe。

3. 插件目录
   plugins\\ 与 exe 同级。新增插件放这里，
   或用环境变量 AUTODOOR_PLUGINS_DIR 指定其他位置。

4. 工作目录
   assets / logs 等运行期产物都落在本目录，不要放在 _internal 内。

5. 已知限制
   打包版未包含 REST 服务依赖，run --rest / daemon 的 HTTP 接口不可用。
   需要 REST 时请使用源码 + venv 方式部署。
"""


def main(argv) -> int:
    if len(argv) < 3:
        print("usage: python generate_launcher_notes.py <version> <output_dir>")
        return 2

    version, out_dir = argv[1], argv[2]
    if not os.path.isdir(out_dir):
        print("output dir not found: %s" % out_dir)
        return 1

    target = os.path.join(out_dir, "launcher-notes.txt")
    with io.open(target, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(TEMPLATE.format(version=version))

    print("launcher notes written: %s" % target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
