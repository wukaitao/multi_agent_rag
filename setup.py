# 使用 Cython 编译核心模块
import glob
import os
import shutil
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
from Cython.Build import cythonize

# 自定义编译后置清理
class CustomBuildExt(build_ext):
    def run(self):
        # 先执行正常编译生成 pyd
        build_ext.run(self)

        # ========== 编译后自动清理 ==========
        # 1. 删除根目录 build 文件夹
        build_dir = "build"
        if os.path.isdir(build_dir):
            shutil.rmtree(build_dir)
            print(f"已删除根目录 build/")

        # 2. 删除 agents 下全部 .c 中间文件
        c_files = glob.glob("agents/*.c")
        for c in c_files:
            os.remove(c)
        print(f"已删除 {len(c_files)} 个 agents/*.c 文件")

# 自动读取agents下全部.py
src_list = glob.glob("agents/*.py")
ext_list = []

for src_path in src_list:
    # 模块名必须 agents.xxx，--inplace才会输出到agents文件夹
    mod_name = src_path.replace("\\", ".").replace(".py", "")
    ext_list.append(Extension(mod_name, sources=[src_path]))

setup(
    name="multi-agent-core",
    ext_modules=cythonize(
        ext_list,
        compiler_directives={
            "language_level": 3,
            "boundscheck": False,
            "wraparound": False
        }
    ),
    # 注册自定义编译命令
    cmdclass={"build_ext": CustomBuildExt},
    zip_safe=False,
    packages=[],               # 手动置空, 关闭自动扫描包, 只编译 protected_modules 配置
    py_modules=[]
)