#!/usr/bin/env python3

import fileinput
from io import StringIO
import re
from typing import TextIO

MODULE_SPLIT_RE = re.compile(r'(.*)module\s+(\w+)(.+)endmodule.*', re.DOTALL)
PARAMETER_SPLIT_RE = re.compile(r'\s*#\((.*?)\)\s*(\(.*)', re.DOTALL)
SIGNAL_SPLIT_RE = re.compile(r'\s*\((.*?)\).*', re.DOTALL)

def process_code(code):
    m = MODULE_SPLIT_RE.fullmatch(code)
    if m is None:
        raise ValueError('Invalid module definition')
    
    imports_and_directives = []
    parameter_spec = {}
    signal_spec = {}
    interface_spec = {}
    
    pre, module_name, definition = m.groups()
    
    for line in pre.splitlines():
        line = line.strip()
        if line.startswith('import') or line.startswith('`'):
            imports_and_directives.append(line)
    
    p = PARAMETER_SPLIT_RE.fullmatch(definition)
    if p is not None:
        parameters, definition = p.groups()
        
        for parameter in parameters.split(','):
            parts = parameter.split('=')
            declaration_tokens = parts[0].split()
            default_tokens = parts[1].split() if len(parts) > 1 else []
            
            kind = declaration_tokens[0]
            name = declaration_tokens[-1]
            
            if kind != 'parameter':
                continue
            
            parameter_spec[name] = dict(declaration_tokens=declaration_tokens)
            if default_tokens:
                parameter_spec[name]['default_tokens'] = default_tokens
    
    s = SIGNAL_SPLIT_RE.fullmatch(definition)
    if s is not None:
        signals = s.group(1)
        
        for signal in signals.split(','):
            declaration_tokens = signal.split()
            
            kind = declaration_tokens[0]
            name = declaration_tokens[-1]
            skip_in_top = False
            
            if kind != 'input' and kind != 'output':
                int_name = kind.split('.')[0]
                interface_spec[name] = dict(interface=int_name)
                skip_in_top = True
            
            signal_spec[name] = dict(
                declaration_tokens=declaration_tokens,
                skip_in_top=skip_in_top,
            )
    
    with StringIO() as gen:
        if imports_and_directives:
            gen.write('\n'.join(imports_and_directives))
            gen.write('\n\n')
        
        gen.write(f'module {module_name}__flat_top')
        
        if parameter_spec:
            gen.write(' #(\n')
            for idx, (name, spec) in enumerate(parameter_spec.items()):
                gen.write(f'  {' '.join(spec['declaration_tokens'])}')
                if 'default_tokens' in spec:
                    gen.write(f' = {" ".join(spec["default_tokens"])}')
                if idx != len(parameter_spec) - 1:
                    gen.write(',')
                gen.write(f'\n')
            gen.write(')')
        
        top_signal_spec = { k: v for k, v in signal_spec.items() if not v['skip_in_top']}
        if top_signal_spec:
            gen.write(' (\n')
            for idx, (name, spec) in enumerate(top_signal_spec.items()):
                gen.write(f'  {' '.join(spec['declaration_tokens'])}')
                if idx != len(top_signal_spec) - 1:
                    gen.write(',')
                gen.write(f'\n')
            gen.write(')')
        
        gen.write(f';\n\n')
        
        if interface_spec:
            for name, spec in interface_spec.items():
                gen.write(f'  {spec['interface']} {name}();\n')
            gen.write('\n')
        
        gen.write(f'  {module_name}')
        
        if parameter_spec:
            gen.write(' #(\n')
            for idx, (name, spec) in enumerate(parameter_spec.items()):
                gen.write(f'    .{name}({name})')
                if idx != len(parameter_spec) - 1:
                    gen.write(',')
                gen.write(f'\n')
            gen.write('  )')
        
        gen.write(f' dut')
        
        if signal_spec:
            gen.write(' (\n')
            for idx, (name, spec) in enumerate(signal_spec.items()):
                gen.write(f'    .{name}({name})')
                if idx != len(signal_spec) - 1:
                    gen.write(',')
                gen.write(f'\n')
            gen.write('  )')
        
        gen.write(';\n\n')
    
        gen.write(f'endmodule\n')
    
        return gen.getvalue()

def process_file(file: TextIO | fileinput.FileInput) -> str:
    code = ''
    for line in file:
        code += line.split('//')[0]
    
    return process_code(code)

def process_file_and_write(file: TextIO | fileinput.FileInput, output_file: TextIO):
    output_file.write(process_file(file))

def main():
    with fileinput.input() as f:
        print(process_file(f))

if __name__ == '__main__':
    main()