def gen_code(prompt: str) -> str:
    code = f"""# {prompt}
def demo():
    print("AI 代码生成成功")
    return True
demo()
"""
    return f"```python\n{code}\n```"