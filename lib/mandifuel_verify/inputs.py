"""Literal OpenFOAM dictionaries, without evaluating directives or macros."""
import math
import re


class Unavailable(ValueError):
    """A necessary fact cannot be established from the saved evidence."""


def dictionary(text):
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}();\[\]]|[^\s{}();\[\]]+', text)
    index = 0

    def block(nested=False):
        nonlocal index
        result = {}
        while index < len(tokens):
            key = tokens[index].strip('"'); index += 1
            if key == '}':
                if not nested: raise Unavailable('字典括号不匹配')
                return result
            if key == ';': continue
            if key.startswith('#'):
                result.setdefault('_directives', []).append(key)
                # Directives are never executed. Their scope cannot be certified.
                if index < len(tokens): index += 1
                continue
            if index >= len(tokens): raise Unavailable('字典条目未保存完整：' + key)
            if tokens[index] == '{':
                index += 1; value = block(True)
            else:
                value = []; stack = []
                while index < len(tokens):
                    token = tokens[index]; index += 1
                    if token == ';' and not stack: break
                    if token in ('(', '['): stack.append(token)
                    elif token in (')', ']'):
                        if not stack or stack.pop() != {')': '(', ']': '['}[token]: raise Unavailable('列表括号不匹配')
                    elif token in ('{', '}'): raise Unavailable('未支持或未完整保存的字典表达式：' + key)
                    value.append(token)
                else: raise Unavailable('字典条目缺少分号：' + key)
            if key in result: result.setdefault('_duplicates', []).append(key)
            result[key] = value
        if nested: raise Unavailable('字典尚未保存完整')
        return result
    return block()


def get(tree, *path):
    for key in path:
        if not isinstance(tree, dict) or tree.get('_directives') or key in tree.get('_duplicates', []):
            raise Unavailable('输入含未解析指令或重复条目：' + '/'.join(path))
        if key not in tree: raise Unavailable('缺少明确输入：' + '/'.join(path))
        tree = tree[key]
    return tree


def word(tree, *path):
    tokens = get(tree, *path)
    if not isinstance(tokens, list) or len(tokens) != 1: raise Unavailable('需要明确的单值输入：' + '/'.join(path))
    return tokens[0].strip('"')


def scalar(tree, *path, dimensions=None):
    tokens = get(tree, *path)
    if not isinstance(tokens, list) or not tokens: raise Unavailable('需要明确的标量输入：' + '/'.join(path))
    # Plain scalar, uniform scalar, or a dimensioned scalar; no macro evaluation.
    prefix = tokens[:-1]
    if prefix and prefix != ['uniform'] and '[' not in prefix: raise Unavailable('未支持的标量表达式：' + '/'.join(path))
    if '[' in prefix:
        try:
            start,end = prefix.index('['),prefix.index(']')
            dims = [float(v) for v in prefix[start+1:end]]
            if len(dims) not in {5,7} or end!=len(prefix)-1 or start>1: raise ValueError()
            dims += [0]*(7-len(dims))
            if dimensions is not None and dims!=list(dimensions): raise ValueError()
        except (ValueError,TypeError): raise Unavailable('输入量纲或表达式不符合定义：' + '/'.join(path)) from None
    try: value = float(tokens[-1])
    except (TypeError, ValueError): raise Unavailable('输入不是常数：' + '/'.join(path)) from None
    if not math.isfinite(value): raise Unavailable('输入包含非有限数值')
    return value


def zero_vector(tree, *path):
    tokens = get(tree, *path)
    if tokens[:1] == ['uniform']: tokens = tokens[1:]
    try:return len(tokens)==5 and tokens[0]=='(' and tokens[-1]==')' and all(float(v)==0 for v in tokens[1:4])
    except ValueError:return False
