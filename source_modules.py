"""Load legacy source modules under private names without changing sys.path.

Only imports of explicitly listed sibling modules are rebound. Source files,
collectors and their globals stay separate from the football-odds modules.
"""
import ast
import sys
from pathlib import Path
from types import ModuleType


def load_source_package(package_name, directory, module_names):
    directory = Path(directory)
    package = ModuleType(package_name)
    package.__path__ = [str(directory)]
    package.__file__ = str(directory / "app.py")
    sys.modules[package_name] = package

    class LocalImports(ast.NodeTransformer):
        def visit_Import(self, node):
            statements = []
            for alias in node.names:
                if alias.name in module_names:
                    statement = ast.ImportFrom(
                        module=package_name,
                        names=[ast.alias(name=alias.name, asname=alias.asname)],
                        level=0,
                    )
                else:
                    statement = ast.Import(names=[alias])
                statements.append(ast.copy_location(statement, node))
            return statements

    # Dependencies precede their consumers; no module is executed as __main__.
    for name in module_names:
        path = directory / (name + ".py")
        qualified = package_name + "." + name
        module = ModuleType(qualified)
        module.__file__ = str(path)
        module.__package__ = package_name
        sys.modules[qualified] = module
        setattr(package, name, module)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        tree = ast.fix_missing_locations(LocalImports().visit(tree))
        exec(compile(tree, str(path), "exec"), module.__dict__)
    return package.app
