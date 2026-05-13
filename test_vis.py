from cadquery import *
from cadquery.func import *
from cadquery.vis import show

w = Workplane().sphere(0.5).split(keepTop=True)
sk = Sketch().rect(1.5, 1.5)
sh = torus(5, 0.5)

r = rect(2, 2)
c = circle(2)

N = 50
params = [i/N for i in range(N)]

vecs = r.positions(params)
locs = c.locations(params)

# Render the solid
show(w, sk, sh, vecs, locs)