#!/usr/bin/env python3
# encoding: utf-8

"""
ptb.py: Module for reading and transforming trees in the Penn Treebank
format.

Author: Joseph Irwin
Modifications: Aditya Bhargava (labelled phrases output)

To the extent possible under law, the person who associated CC0 with
this work has waived all copyright and related or neighboring rights
to this work.
http://creativecommons.org/publicdomain/zero/1.0/
"""


import re


#######
# Utils
#######

def gensym():
    return object()


##################
# Lexer
##################


LPAREN_TOKEN = gensym()
RPAREN_TOKEN = gensym()
STRING_TOKEN = gensym()

class Token(object):
    _token_ids = {LPAREN_TOKEN:"(", RPAREN_TOKEN:")", STRING_TOKEN:"STRING"}

    def __init__(self, token_id, value=None, lineno=None):
        self.token_id = token_id
        self.value = value
        self.lineno = lineno

    def __str__(self):
        return "Token:'{tok}'{ln}".format(
            tok=(self.value if self.value is not None else self._token_ids[self.token_id]),
            ln=(':{}'.format(self.lineno) if self.lineno is not None else '')
            )


_token_pat = re.compile(r'\(|\)|[^()\s]+')
def lex(line_or_lines):
    """
    Create a generator which returns tokens parsed from the input.

    The input can be either a single string or a sequence of strings.
    """

    if isinstance(line_or_lines, str):
        line_or_lines = [line_or_lines]

    for n,line in enumerate(line_or_lines):
        line.strip()
        for m in _token_pat.finditer(line):
            if m.group() == '(':
                yield Token(LPAREN_TOKEN)
            elif m.group() == ')':
                yield Token(RPAREN_TOKEN)
            else:
                yield Token(STRING_TOKEN, value=m.group())


##################
# Parser
##################


class Symbol:
    _pat = re.compile(r'(?P<label>^[^0-9=-]+)|(?:-(?P<tag>[^0-9=-]+))|(?:=(?P<parind>[0-9]+))|(?:-(?P<coind>[0-9]+))')
    def __init__(self, label):
        self.label = label
        self.tags = []
        self.coindex = None
        self.parindex = None
        self.parent = None
        for m in self._pat.finditer(label):
            if m.group('label'):
                self.label = m.group('label')
            elif m.group('tag'):
                self.tags.append(m.group('tag'))
            elif m.group('parind'):
                self.parindex = m.group('parind')
            elif m.group('coind'):
                self.coindex = m.group('coind')

    def simplify(self, keep_sbj=False):
        ts = self.tags
        if 'SBJ' in ts and keep_sbj:
            ts = ['SBJ']
        else:
            ts = []
        self.tags = ts
        self.coindex = None
        self.parindex = None
        self.parent = None

    def __str__(self):
        return '{}{}{}{}{}'.format(
            self.label,
            ''.join('-{}'.format(t) for t in self.tags),
            ('={}'.format(self.parindex) if self.parindex is not None else ''),
            ('-{}'.format(self.coindex) if self.coindex is not None else ''),
            ('^{}'.format(self.parent) if self.parent is not None else '')
        )

class Leaf:
    def __init__(self, word, pos):
        self.word = word
        self.pos = pos

class TExpr:
    def __init__(self, head, first_child, next_sibling):
        self.head = head
        self.first_child = first_child
        self.next_sibling = next_sibling

    def symbol(self):
        if hasattr(self.head, 'label'):
            return self.head
        else:
            return None

    def children(self):
        n = self.first_child
        while n is not None:
            yield n
            n = n.next_sibling

    def leaf(self):
        if hasattr(self.head, 'pos'):
            return self.head
        else:
            return None

    def rule(self):
        if self.leaf():
            return '{} -> {}'.format(self.leaf().pos, self.leaf().word)
        else:
            return '{} -> {}'.format(self.symbol(), ' '.join(str(c.symbol() or c.leaf().pos) for c in self.children()))

    def rule_tpl(self):
        if self.leaf():
            return (self.leaf().pos, self.leaf().word)
        else:
            return (str(self.symbol()), ' '.join(str(c.symbol() or c.leaf().pos) for c in self.children()))

    def __str__(self):
        if self.leaf():
            return '({} {})'.format(self.leaf().pos, self.leaf().word)
        else:
            return '({} {})'.format(
                self.head if self.head is not None else '',
                ' '.join(str(c) for c in self.children())
            )


def parse(line_or_lines):
    def istok(t, i):
        return getattr(t, 'token_id', None) is i
    stack = []
    for tok in lex(line_or_lines):
        if tok.token_id is LPAREN_TOKEN:
            stack.append(tok)
        elif tok.token_id is STRING_TOKEN:
            stack.append(tok)
        else:
            if (istok(stack[-1], STRING_TOKEN) and
                istok(stack[-2], STRING_TOKEN) and
                istok(stack[-3], LPAREN_TOKEN)):
                w = Leaf(stack[-1].value, stack[-2].value)
                stack.pop()
                stack.pop()
                stack.pop()
                stack.append(TExpr(w, None, None))
            else:
                tx = None
                tail = None
                while not istok(stack[-1], LPAREN_TOKEN):
                    head = stack.pop()
                    if istok(head, STRING_TOKEN):
                        tx = TExpr(
                            Symbol(head.value),
                            first_child = tail,
                            next_sibling = None
                        )
                    else:
                        head.next_sibling = tail
                        tail = head
                stack.pop()
                if tx is None:
                    tx = TExpr(None, tail, None)
                if not stack:
                    yield tx
                else:
                    stack.append(tx)


##################
# Traversal
##################

def traverse(tx, pre=None, post=None, state=None):
    """
    Traverse a tree.

    Allows pre-, post-, or full-order traversal. If given, `pre` and
    `post` should be functions or callable objects accepting two
    arguments: a TExpr node and a state object. If the state is used,
    `pre` and `post` should return a new state object.
    """
    if pre is not None:
        state = pre(tx, state)
    for c in tx.children():
        state = traverse(c, pre, post, state)
    if post is not None:
        state = post(tx, state)
    return state


##################
# Transforms
##################


def remove_empty_elements(tx):
    q_none = gensym()
    q_ok = gensym()
    state = [[]]

    def pre(tx, st):
        if tx.leaf() is None:
            return st + [[]]
        else:
            return st

    def post(tx, st):
        q = q_ok
        if tx.leaf():
            q = q_none if tx.leaf().pos == '-NONE-' else q_ok
        else:
            cs = st.pop()
            cs = [c for q,c in cs if q is q_ok]
            if cs:
                tx.first_child = cs[0]
                for c,d in zip(cs[:-1],cs[1:]):
                    c.next_sibling = d
                cs[-1].next_sibling = None
            else:
                q = q_none
        st[-1].append( (q, tx) )
        return st

    state = traverse(tx, pre, post, state)


def simplify_labels(tx, keep_sbj=False):
    def proc(tx, st):
        if tx.symbol():
            tx.symbol().simplify(keep_sbj)
    traverse(tx, proc)

def annot_parent(tx, keep_sbj=False):
    def pre(tx, st):
        s = ''
        if tx.symbol():
            s = '-'.join([tx.symbol().label] + tx.symbol().tags)
        # else:
        #     s = tx.leaf().pos
        if st:
            parent = st[-1]
            if tx.symbol():
                tx.symbol().parent = parent
            # else:
            #     tx.leaf().pos = str(tx.leaf().pos) + '^' + parent
        return st + [s]
    def post(tx, st):
        return st[:-1]
    traverse(tx, pre, post, state=[])

def remove_parent(tx, keep_sbj=False):
    def pre(tx, st):
        if tx.symbol():
            tx.symbol().label = tx.symbol().label.split('^')[0]
        else:
            tx.leaf().pos = tx.leaf().pos.split('^')[0]
    traverse(tx, pre)

def mark_top(tx, keep_sbj=False):
    cs = list(tx.children())
    assert(len(cs) == 1)
    cs[0].symbol().parent = 'ROOT'
    return tx


_dummy_labels = ('ROOT', 'TOP')
def add_root(tx, root_label='ROOT'):
    if (tx.head is None or (tx.symbol() and tx.symbol().label in _dummy_labels)):
        tx.head = Symbol(root_label)
    else:
        tx = TExpr(Symbol(root_label), tx)
    return tx


##################
# Other Useful Functions
##################

def all_rules(tx):
    """
    Returns a list of the production rules in a tree.
    """
    def pre(tx, st):
        if tx.leaf():
            return st
        return st + [tx.rule()]
    return traverse(tx, pre, state=[])

def grammar_rules(tx):
    """
    Returns a list of the production rules in a tree.
    Rules are pairs like: (lhs, [rhs]). Includes lexical rules
    """
    def pre(tx, st):
        return st + [tx.rule_tpl()]
    return traverse(tx, pre, state=[])


def all_spans(tx):
    """
    Returns a list of spans in a tree. The spans are in depth-first
    traversal order.
    """
    state = ([], [], 0, 0)

    def pre(tx, st):
        spans, stack, begin, count = st
        return (
            spans,
            stack + [(count, begin)],
            begin,
            count + 1
        )

    def post(tx, st):
        spans, stack, end, count = st
        num, begin = stack.pop()

        label = None
        if tx.leaf():
            if tx.leaf().pos != '-NONE-':
                end = begin + 1
            label = tx.leaf().pos
        elif tx.symbol():
            label = str(tx.symbol())

        if label:
            spans.append((num, (label, begin, end)))

        return (
            spans,
            stack,
            end,
            count
        )

    spans, _, _, _ = traverse(tx, pre, post, state)
    spans.sort()
    return [s for n,s in spans]


##################
# Parse Tree
##################

class Span(object):
    def __init__(self, label, begin, end):
        self.label = label
        self.begin = begin
        self.end = end

    def tojson(self):
        return [self.label and str(self.label), self.begin, self.end]


class AnchoredTree(object):
    def __init__(self, spans, edges):
        self.spans = spans
        self.edges = edges

    def tojson(self):
        return {
            "spans" : [s.tojson() for s in self.spans],
            "edges" : self.edges
        }


class ParsedSentence(object):
    def __init__(self, terminals, tree):
        self.terminals = terminals
        self.tree = tree

    def _index(self, begin_or_span=0, end=None):
        b = begin_or_span
        try:
            if end is None:
                return self.terminals[b:]
            else:
                return self.terminals[b:end]
        except TypeError:
            try:
                return self.terminals[b.span.begin:b.span.end]
            except AttributeError:
                return self.terminals[b.begin:b.end]

    def words(self, begin_or_span=0, end=None):
        for t in self._index(begin_or_span, end):
            yield t.word

    def tagged_words(self, begin_or_span=0, end=None):
        for t in self._index(begin_or_span, end):
            yield (t.pos, t.word)

    def tags(self, begin_or_span=0, end=None):
        for t in self._index(begin_or_span, end):
            yield t.pos

    def tojson(self):
        return {
            "parse" : self.tree.tojson(),
            "words" : [t.word for t in self.terminals],
            "tags" : [t.pos for t in self.terminals]
        }


TERMINAL_NODE_LABEL = '<t>'
def make_anchored(tx):
    state = (
        [],            # [<begin>] (pre)→(post) [(<span>, (<index>, [<child_indices>]) | None)]
        [(-1, [])],    # [(<index>, <child_indices>)]
        0,             # next_index
        0              # current_offset
    )

    def pre(tx, st):
        "save post-order index and current token offset"
        nodes, stack, index, begin = st
        return (
            nodes + [begin],
            stack + [(index, [])],
            index + 1,
            begin
        )

    def post(tx, st):
        "save span and edge to <nodes> at <index>"
        nodes, stack, next_index, end = st
        index, children = stack.pop()

        if tx.leaf():
            end += 1

        begin = nodes[index]
        nodes[index] = (
            Span(
                tx.symbol(),
                begin,
                end
            ),
            (index, children) if not tx.leaf() else None
        )

        stack[-1][-1].append(index)
        return (nodes, stack, next_index, end)

    nodes, _, _, _ = traverse(tx, pre, post, state)
    spans = [s for s,e in nodes]
    edges = [e for s,e in nodes if e]
    return AnchoredTree(spans, edges)

def leaves(tx):
    def proc(tx, st):
        return st + ([tx.leaf()] if tx.leaf() else [])
    return traverse(tx, proc, state=[])

def labelled_phrases(tx):
    def proc(tx, st):
        label = tx.symbol()
        if not label:
            label = tx.leaf().pos
        else:
            label = label.label
        return st + ['\t'.join([' '.join(l.word for l in leaves(tx)), label])]
    return traverse(tx, proc, state=[])

def rl_sentence(tx):
    return '\t'.join([tx.symbol().label, leaves(tx)])

def make_parsed_sent(tx):
    return ParsedSentence(leaves(tx), make_anchored(tx))


##################
# Main
##################


def main(args):
    """
    Usage:
      ptb process [options] [--] <file>
      ptb test
      ptb -h | --help

    Options:
      --add-root                Add a root node to the tree.
      -r=ROOT --root=ROOT       Specify label of root node. [default: ROOT]
      --simplify-labels         Simplify constituent labels.
      --keep-sbj-tags           Preserve -SBJ tags when simplifying labels [default: False]
      --annotate-parent         Add parent label annotation to tree node labels. [default: False]
      --remove-parent           Remove parent label annotation from tree node labels. [default: False]
      --mark-top                Mark the top constituent with ^ROOT. [default: False]
      --remove-empties          Remove empty elements.
      --format FMT              Specify format to output trees in. [default: phrases]
      -h --help                 Show this screen.

    Support output formats are: ptb, json, sentence, tagged_sentence, rules, grammar, phrases, rl_sentence.
    """
    from docopt import docopt
    args = docopt(main.__doc__, argv=args)

    def trans(t):
        if args['--remove-empties']:
            remove_empty_elements(t)
        if args['--simplify-labels']:
            simplify_labels(t, args['--keep-sbj-tags'])
        if args['--add-root']:
            t = add_root(t, root_label=args['--root'])
        if args['--annotate-parent']:
            annot_parent(t)
        if args['--remove-parent']:
            remove_parent(t)
        if args['--mark-top']:
            mark_top(t)
        return t

    def trees():
        if args['<file>'] == '-':
            for t in parse(sys.stdin):
                yield trans(t)
        else:
            with open(args['<file>'], 'r') as f:
                for t in parse(f):
                    yield trans(t)

    if args['process']:
        fmt = args['--format']
        if fmt == 'json':
            import json
            o = {'sentences' : [make_parsed_sent(t).tojson() for t in trees()]}
            print(json.dumps(o))
        elif fmt == 'rules':
            import collections
            rules = collections.Counter(
                r
                for t in trees()
                for r in all_rules(t)
            )
            for r,c in rules.most_common():
                print(r,c,sep='\t')
        elif fmt == 'grammar':
            import collections
            rules = collections.Counter(
                r
                for t in trees()
                for r in grammar_rules(t)
            )
            gram = dict()
            for r,c in rules.most_common():
                gram.setdefault(r[0], []).append((r[1], c))
            for lhs in gram:
                total = float(sum(c for rhs,c in gram[lhs]))
                for rhs,c in gram[lhs]:
                    print('{} -> {}\t{}'.format(lhs, rhs, c/total))
        else:
            for t in trees():
                # output
                if fmt == 'ptb':
                    print(t)
                elif fmt == 'sentence':
                    print(' '.join(l.word for l in leaves(t)))
                elif fmt == 'tagged_sentence':
                    print(' '.join('_'.join((l.word,l.pos)) for l in leaves(t)))
                elif fmt == 'phrases':
                    for phrase in labelled_phrases(t):
                        print(phrase)
                elif fmt == 'rl_sentence':
                    print('\t'.join([' '.join(l.word for l in leaves(t)),
                                     t.symbol().label]))
                else:
                    raise ValueError()

    if args['test']:
        dotests()

if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
