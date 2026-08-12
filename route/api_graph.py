from .tool.func import *

async def api_graph(name = 'Test'):
    with get_db_connect() as conn:
        curs = conn.cursor()

        # Forward links (from name to other docs)
        curs.execute(db_change("select link from back where title = ?"), [name])
        forward_links = [data[0] for data in curs.fetchall()]

        # Backlinks (from other docs to name)
        curs.execute(db_change("select title from back where link = ?"), [name])
        back_links = [data[0] for data in curs.fetchall()]

        color1 = flask.request.args.get('color1', '#888888')
        color2 = flask.request.args.get('color2', '#cccccc')

        nodes_set = set([name] + forward_links + back_links)
        
        # Format for vis.js
        nodes = []
        for n in nodes_set:
            if n == name:
                nodes.append({"id": n, "label": n, "color": color1, "size": 25}) # current node
            else:
                nodes.append({"id": n, "label": n, "color": color2, "size": 15})

        edges = []
        # Add edges, avoid duplicates
        added_edges = set()
        for l in forward_links:
            edge_str = f"{name}->{l}"
            if edge_str not in added_edges:
                edges.append({"from": name, "to": l})
                added_edges.add(edge_str)
                
        for l in back_links:
            edge_str = f"{l}->{name}"
            if edge_str not in added_edges:
                edges.append({"from": l, "to": name})
                added_edges.add(edge_str)

        return flask.jsonify({
            "nodes": nodes,
            "edges": edges
        })
