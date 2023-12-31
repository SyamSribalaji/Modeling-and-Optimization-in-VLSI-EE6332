# -*- coding: utf-8 -*-
"""EE6632-final.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1KmXDHGqikk4sfohFNZ6EV-HdbjKs85gb
"""

import re
import sys
import random
from pylab import *
sys.setrecursionlimit(30000)
from collections import defaultdict, OrderedDict

"""GPkit"""

!curl https://download.mosek.com/stable/8.1.0.82/mosektoolslinux64x86.tar.bz2 --output /root/mosektoolslinux64x86.tar.bz2
!cd /root/; tar xvf /root/mosektoolslinux64x86.tar.bz2
from google.colab import drive
drive.mount('/content/gdrive')
!cp -avr /content/gdrive/My\ Drive/Mosek/mosek.lic /root/mosek/
!pip install git+https://github.com/convexengineering/gpkit
!pip show gpkit
from gpkit import VectorVariable, Variable, Model, units

#@title Parameters
CL              = 1000
tau             = 5                 # Intrinsic delay of the inverter (in pico seconds)
max_gate_size   = 32
min_gate_size   = 1
C_max_pi        = 50

#@title DAG definition
class DAG:
    def __init__(self):
        self.vertices = {}

    def add_vertex(self, vertex, label=None, depth = None):
        if vertex in self.vertices:
            if self.vertices[vertex]["in"]!= set():
                return
        self.vertices[vertex] = {"in": set(), "out": set(), "label": label, "depth": depth, "atime":-1, "gsize":-1, "delay":0, "slack":-1, "dpath_delay":-1}

    def add_edge(self, from_vertex, to_vertex):
        if from_vertex not in self.vertices:
            self.add_vertex(from_vertex)
        if to_vertex not in self.vertices:
            self.add_vertex(to_vertex)
        self.vertices[from_vertex]["out"].add(to_vertex)
        self.vertices[to_vertex]["in"].add(from_vertex)

    def remove_vertex(self, vertex):
        if vertex not in self.vertices:
            return
        in_edges = self.vertices[vertex]["in"].copy()
        out_edges = self.vertices[vertex]["out"].copy()
        self.vertices.pop(vertex)
        for edge in in_edges:
            self.vertices[edge]["out"].discard(vertex)
        for edge in out_edges:
            self.vertices[edge]["in"].discard(vertex)

    def remove_edge(self, from_vertex, to_vertex):
        if from_vertex not in self.vertices or to_vertex not in self.vertices:
            return
        self.vertices[from_vertex]["out"].discard(to_vertex)
        self.vertices[to_vertex]["in"].discard(from_vertex)

    def get_vertex_label(self, vertex):
        if vertex not in self.vertices:
            return None
        return self.vertices[vertex]["label"]

    def get_vertex_fanout(self, vertex):        ### Returns fanout of vertex
        if vertex not in self.vertices:
            return None
        return self.vertices[vertex]["out"]

    def get_vertex_fanin(self, vertex):         ### Returns fanin of vertex
        if vertex not in self.vertices:
            return None
        return self.vertices[vertex]["in"]

    def get_vertex_depth(self,vertex):          ### Returns depth of given vertex
        return self.vertices[vertex]["depth"]

    def get_vertex_gsize(self,vertex):          ### Returns gsize of given vertex
        return self.vertices[vertex]["gsize"]

    def get_vertex_atime(self,vertex):          ### Returns atime of given vertex
        return self.vertices[vertex]["atime"]

    def get_label_fanout(self,label):           ### Returns label of fanout of vertex of given label
        vertex = self.get_label_vertex(label)
        fanout_signals = self.get_vertex_fanout(vertex)
        for sig in list(fanout_signals):
            print(self.get_vertex_label(str(sig)))

    def get_label_vertex(self, label):          ### Returns vertex of label
        xx=0
        for entry in list(self.vertices.values()):
            if(label==entry["label"]):
                xx= list(self.vertices.values()).index(entry)
                return list(self.vertices.keys())[xx]
        return None ## label doesnt exist

    def display(self):                          ### Display all nodes
        for vertex in self.vertices:
            print(vertex,self.vertices[vertex])

    def calc_depths_starter(self):              ### Starts depth calculation for each vertex

        for vertex in self.vertices:
            if(self.vertices[vertex]["depth"]==None):
                self.calc_depths(vertex)
        max=self.find_max_depth(list(self.vertices.keys()))[0]
        self.MAX_NUM=max

    def calc_depths(self,vertex):               ###

            fanin = self.get_vertex_fanin(vertex)                           # if no fanin, it's PI. Already set to 0. return
            if fanin==set():
                return
            depths= []
            for f in fanin:
                d = self.get_vertex_depth(f)                                # get depth of fanin element
                if d == None:                                               # if depth of fanin element is not known, calculate its depth-recursion
                    self.calc_depths(f)
                d = self.get_vertex_depth(f)
                depths.append(d)
            self.vertices[vertex]["depth"] = 1 + max(depths)                # depth

    def calc_path(self,path):                   ### Here fanout refers to the 'tree'- {max:['po'],'po':'fi1_po','fi1_po':fi_fi1 ...} -not circuit

        try:
            fanout = self.previous_max[path[-1]]
        except:
            self.main_list_num.append(path)
            return
        if len(fanout) == 1:
            path.append(fanout[0])
            self.calc_path(path)
        elif len(fanout) > 1:
            for fo in fanout:
                pathcopy=path.copy()
                pathcopy.append(fo)
                self.calc_path(pathcopy)
        return

    def calc_path_at(self,path):                ### Here fanout refers to the 'tree'- {max:['po'],'po':'fi1_po','fi1_po':fi_fi1 ...} -not circuit

        try:
            fanout = self.prev_max[path[-1]]
        except:
            self.main_list_at.append(path)
            return

        if len(fanout) == 1:
            path.append(fanout[0])
            self.calc_path_at(path)
        elif len(fanout) > 1:
            for fo in fanout:
                pathcopy=path.copy()
                pathcopy.append(fo)
                self.calc_path_at(pathcopy)
        return

    def calc_ai_t0(self,gsize,gates,CL,g,p):    ### Calc a_i; returns ai,t0

        ai=[-1 for gate in gates]
        cur_level=1
        while (cur_level <= self.MAX_NUM):
            for i in range(0,len(gates)):
                temp=[]
                d   =0
                if self.get_vertex_depth(gates[i])==cur_level:
                    fanin = self.get_vertex_fanin(gates[i])
                    fanout= self.get_vertex_fanout(gates[i])
                    for k in fanout:
                        d   = d + g[gates.index(k)] * gsize[gates.index(k)]
                    if len(fanout)==0:
                        d   = CL
                    d   = d/gsize[i]
                    d   = d + p[i]
                    for l in fanin:
                        try:
                            temp.append(ai[gates.index(l)]+ d)
                        except:
                            temp.append(d)                      #PI
                    ai[i]   = max(temp)
            cur_level += 1
        self.update_ai_x(ai,gsize,gates)
        # self.update_delays(CL,gates,g,p,gsize)                # instead we will call this when working with slack alone
        return ai,max(ai)

    def find_max_depth(self,vertices):          ### Finds(returns) maximum depth given a set of vertices

        depths=[]
        max_ind=[]
        max=0
        for i in range(0,len(vertices)):
            d = self.get_vertex_depth(vertices[i])
            depths.append(d)
            if(d>max):                                                      # max computation
                max = d
                max_ind=[]
                max_ind.append(vertices[i])
            elif(d==max):
                max_ind.append(vertices[i])
        return max,max_ind

    def find_max_atime(self,vertices):          ### Finds(returns) maximum atime given a set of vertices

        atimes=[]
        max_ind=[]
        max=0
        for i in range(0,len(vertices)):
            at = self.get_vertex_atime(vertices[i])
            atimes.append(at)
            if(at>max):                                                      # max computation
                max = at
                max_ind=[]
                max_ind.append(vertices[i])
            elif(at==max):
                max_ind.append(vertices[i])
        # print(atimes)
        # print(max,max_ind)
        return max,max_ind

    def find_longest(self):                     ### Finds longest path(s)-num of gates

        self.main_list_num=[]                                               # final list of all longest paths
        self.calc_depths_starter()
        max,max_ind=self.find_max_depth(list(self.vertices.keys()))         # max_ind: list of vertices with maximum depth
        self.MAX_NUM=max
        self.previous_max={}
        self.previous_max[max]=max_ind
        while max:
            stage_list=[]
            for ind in max_ind:
                vertices = list(self.get_vertex_fanin(ind))                 # go back one stage
                m,prev = self.find_max_depth(vertices)                      # max at that stage
                self.previous_max[ind]=prev
                stage_list.append(prev)
            max_ind=[item for sublist in stage_list for item in sublist]    # flatten lists
            max = max -1
        for po in self.previous_max[self.MAX_NUM]:
            self.calc_path([po])
        self.main_list_num = list(set([tuple(path[:-1]) for path in self.main_list_num])) # to stop backtracking before PIs

        for path in self.main_list_num:
            print(path)
        print("No of longest paths = ",len(self.main_list_num))
        print("Length of such paths = ",self.MAX_NUM)

    def find_crt_path(self):                    ### Finds critical path(s)

        self.main_list_at=[]                                                # final list of all crt paths
        max,max_ind=self.find_max_atime(list(self.vertices.keys()))         # max_ind: list of vertices with maximum atimes
        self.MAX_AT=max
        self.prev_max={}
        self.prev_max[max]=max_ind

        while max_ind!=[]:
            stage_list=[]
            for ind in max_ind:
                vertices = list(self.get_vertex_fanin(ind))                 # go back one stage
                m,prev = self.find_max_atime(vertices)                      # max at that stage
                if prev!=[]:
                    self.prev_max[ind]=prev
                stage_list.append(prev)
            max_ind=[item for sublist in stage_list for item in sublist]    # flatten lists

        print("PO .... PI")
        for po in self.prev_max[self.MAX_AT]:
            self.calc_path_at([po])

        self.main_list_at = list(set([tuple(path[:-1]) for path in self.main_list_at])) # to stop backtracking before PIs

        for path in self.main_list_at:
            print(path)
        return self.main_list_at

    def update_ai_x(self,ai,gsize,gates):       ### updates ai,x of every gate. called in calc_ai_t0
        for gate in self.vertices.keys():
            try:
                self.vertices[gate]["gsize"]=gsize[gates.index(gate)]
                self.vertices[gate]["atime"]=   ai[gates.index(gate)]
            except:
                self.vertices[gate]["atime"]= 0

    def update_delays(self,CL,gates,g,p,gsize): ### updates delays of every gate. called in calc_ai_t0

        for i in range(0,len(gates)):
            fanout= dag.get_vertex_fanout(gates[i])
            d     = 0
            for k in fanout:
                d   = d + g[gates.index(k)] * gsize[gates.index(k)]/gsize[i] # g_k*x_k/x_i
            if len(fanout)==0:
                d   = d + CL/gsize[i]    #Load Cap
            d     = d + p[i]
            self.vertices[gates[i]]["delay"]=d

    def update_dpaths(self,dict_levels):        ### dpath is longest path to a po(timing)
        level = self.MAX_NUM
        while(level>=0):
            gates= dict_levels[level]
            for gate in gates:
                if(level==self.MAX_NUM):
                    self.vertices[gate]["dpath_delay"]=0
                else:
                    fanout = list(self.get_vertex_fanout(gate))
                    delays = [self.vertices[x]["delay"] for x in fanout]
                    self.vertices[gate]["dpath_delay"] = max(delays) + self.vertices[fanout[delays.index(max(delays))]]["dpath_delay"]
                    # print(gate,max(delays))
            level-=1

    def update_slack(self,CL,gates,inputs,g,p,gsize,Tspec,dict_levels):### updates slack at every gate output
        self.update_delays(CL,gates,g,p,gsize)
        self.update_dpaths(dict_levels)
        for i in range(len(gates)):                     # atime at op + slack + longest path to PO = Tspec
            self.vertices[gates[i]]["slack"] = Tspec - self.vertices[gates[i]]["atime"] - self.vertices[gates[i]]["dpath_delay"]
        for i in range(len(inputs)):
            self.vertices[inputs[i]]["slack"] = Tspec - self.vertices[inputs[i]]["dpath_delay"]

#@title Verilog parser - function
def parse_verilog_netlist(filename):

    with open(filename, "r") as file:
        netlist = file.read()

    # Skip any comment lines before the module declaration
    lines = netlist.splitlines()
    for i, line in enumerate(lines):
        if (line.startswith('//')) or (line==''):
            continue
        else:
            break
    else:
        raise ValueError("No module declaration found")

    module_re = re.compile(r"\s*module\s+(\w+)")
    module_match = module_re.search(lines[i])

    if not module_match:
        raise ValueError("No module declaration found")
    module_name = module_match.group(1)

    # Parse input, output, and wire declarations

    input_re = re.compile(r"\s*input\s+(?:\w+,\s*)*(?:\n\s*(?:\w+,\s*)*)*\w+;")
    output_re = re.compile(r"\s*output\s+(?:\w+,\s*)*(?:\n\s*(?:\w+,\s*)*)*\w+;")
    wire_re   = re.compile(r"\s*wire\s+(?:\w+,\s*)*(?:\n\s*(?:\w+,\s*)*)*\w+;")
    inputs = input_re.findall(netlist)
    outputs = output_re.findall(netlist)
    wires = wire_re.findall(netlist)

    gates = []
    gatetypes=[] ## c880; compatibility
    no_inputs=[]

    for j in range(0,len(inputs)):
        inputs[j]=inputs[j].strip("\n; ")[5:]     ## remove 'input'
        inputs[j]=inputs[j].split(",")
        inputs[j]=[s.strip(" \n") for s in inputs[j]]
    for j in range(0,len(outputs)):
        outputs[j]=outputs[j].strip("\n; ")[6:]     ## remove 'output'
        outputs[j]=outputs[j].split(",")
        outputs[j]=[s.strip(" \n") for s in outputs[j]]
    for j in range(0,len(wires)):
        wires[j]=wires[j].strip("\n; ")[4:]     ## remove 'wire'
        wires[j]=wires[j].split(",")
        wires[j]=[s.strip(" \n") for s in wires[j]]

    inputs = [item for sublist in inputs for item in sublist]
    outputs= [item for sublist in outputs for item in sublist]
    wires  = [item for sublist in wires for item in sublist]

    gate_re = re.compile(r"^\s*(\w+)\s+(\w+)\s*\((.*?)\);")

    dag = DAG()
    for input in inputs:
        dag.add_vertex(input,label = input,depth= 0)
    for gate in gates:
        dag.add_vertex(gate)

    # Parse gate and assign statements
    for line in lines[i+1:]:
        if 'endmodule' in line:
            break
        if '//' in line:
            line = line.split('//')[0]  # remove comments from line
        match = gate_re.match(line)
        if match:
            gate, gate_name, signals = match.groups()
            signals = re.findall(r'\b\w+\b', signals)
            gates.append(gate_name)
            gatetypes.append(gate)
            no_inputs.append(len(signals)-1)
            dag.add_vertex(gate_name,label=signals[0])                ## (gate_name,signal)

    # Create directed acyclic graph (DAG) from gates
    for line in lines[i+1:]:
        if 'endmodule' in line:
            break
        if '//' in line:
            line = line.split('//')[0]  # remove comments from line
        match = gate_re.match(line)
        if match:
            gate, gate_name, signals = match.groups()
            signals = re.findall(r'\b\w+\b', signals)

            l = len(signals)
            for j in range(1,l):
                dag.add_edge(dag.get_label_vertex(signals[j]),dag.get_label_vertex(signals[0]))

    return module_name, inputs, outputs, wires, gates, gatetypes, no_inputs, dag

#@title Calculation of g,p for each gate - function
def calc_g_p(gates,gatetypes):
  g = []  # Logical effort list containing the logical effort for all gates in the circuit
  p = []  # parasitic delay list containing the parasitic delay for all gates in the circuit

  for i in range(len(gates)):
    gate_type = gatetypes[i]
    no_inputs = len(dag.get_vertex_fanin(gates[i]))

#   for gate in gates:
#     gate_type = gate.split("_")[0][:-1]
#     no_inputs = int(gate.split("_")[0][-1])

    p.append(no_inputs)

    if gate_type == "NAND" or gate_type == "nand":
      g.append((no_inputs + 2)/3)
    elif gate_type == "NOR" or gate_type == "nor":
      g.append((2*no_inputs + 1)/3)
    elif gate_type == "NOT" or gate_type == "not":
      g.append(1)
    else:
      print("Netlist not compatible\n",gate)
  return g,p

#@title Adding basic constraints - functions
def add_basic_constraints(dag,gates,inputs,g,p,constraints,CL,Cmax_in,T0,Gsize,Atime):

    for i in range(0,len(inputs)):
        fanout  = dag.get_vertex_fanout(inputs[i])
        exp     = 0
        for k in fanout:
            exp = exp + g[gates.index(k)] * Gsize[gates.index(k)]
        constraints.append(exp          <= Cmax_in)

    for i in range(0,len(gates)):
        constraints.append(Atime[i]  <=  T0)
        # if(dag.get_vertex_depth(gates[i])==1):
        #      print("here")
        #      constraints.append( Gsize[i]*g[i]                         <= Cmax_in) #add for gates level 1

    for i in range(0,len(gates)):
        fanin = dag.get_vertex_fanin(gates[i])
        fanout= dag.get_vertex_fanout(gates[i])

        d     = 0
        for k in fanout:
            d   = d + g[gates.index(k)] * Gsize[gates.index(k)] # g_k*x_k
        if len(fanout)==0:
            d   = d + CL    #Load Cap
        d     = d + p[i] * Gsize[i]

        for l in fanin:
            try:
                constraints.append( d + Atime[gates.index(l)]*Gsize[i]  <=    Atime[i]*Gsize[i])
            except:
                constraints.append( d                                   <=    Atime[i]*Gsize[i]) #Fanin is PI
        ## we dont do a_i = 0 for PIs as PIs are not part of gates

#@title Twall solution - functions
def solve_twall(dag,gates,inputs,g,p,CL,C_max_pi):

    N       = len(gates)  #Number of gates in the circuit
    Gsize   = VectorVariable(N,"x") #Gate size variables defined through the Vectorvariable class in the gpkit library
    Atime   = VectorVariable(N,"a") #Arrival time at output of corresponding gate
    T0      = Variable("T0")
    constraints     = []

    for n in range(0,N):      # Minimum and Maximum - continous solution
        constraints.append(Gsize[n] >= min_gate_size) # Setting lower bounds for gate sizes since the solver requires it
        constraints.append(Gsize[n] <= max_gate_size) # Setting upper bounds for gate sizes since the solver requires it

    add_basic_constraints(dag,gates,inputs,g,p,constraints,CL,C_max_pi,T0,Gsize,Atime)

    objective   = T0
    m           = Model(objective, constraints)
    sol_1       = m.solve(verbosity = 1)
    Twall       = sol_1["variables"]["T0"]

    return sol_1,Twall

#@title Minimim area solution(cont) for Tspec/Twall = f - function
def solve_minarea(dag,gates,inputs,g,p,CL,C_max_pi,f,Twall):

    N       = len(gates)  #Number of gates in the circuit
    Gsize   = VectorVariable(N,"x") #Gate size variables defined through the Vectorvariable class in the gpkit library
    Atime   = VectorVariable(N,"a") #Arrival time at output of corresponding gate
    T0      = Variable("T0")
    constraints     = []
    Tspec   = Twall * f


    for n in range(0,N):      # Minimum and Maximum - continous solution
        constraints.append(Gsize[n] >= min_gate_size) # Setting lower bounds for gate sizes since the solver requires it
        constraints.append(Gsize[n] <= max_gate_size) # Setting upper bounds for gate sizes since the solver requires it

    add_basic_constraints(dag,gates,inputs,g,p,constraints,CL,C_max_pi,T0,Gsize,Atime)
    constraints.append(T0       <= Tspec)

    objective   = Gsize.sum()
    m           = Model(objective, constraints)
    sol_1       = m.solve(verbosity = 1)
    Tout        = sol_1["variables"]["T0"]

    return sol_1,Tout

#@title Gate size adjustment - function
def adjust_size(level,max):                     ### complex size adjustment for disc., not used
    val = level/max

    if(val>0 and val<= 0.96):
        return +1
    else:
        return -1

#@title DAG creation
#c17,c432,c880,c1908,c2670,c3540,c5315,c6288,c7552,ctest

# filename = "/content/gdrive/MyDrive/CourseWork/EE6332/netlists/c17.txt"# Yuk
filename = "/content/gdrive/MyDrive/netlists/c7552.txt" #Syam

module_name, inputs, outputs, wires, gates, gatetypes,no_inputs, dag = parse_verilog_netlist(filename)
g,p             = calc_g_p(gates,gatetypes)     # Effort calculation
dag.calc_depths_starter()


levels          = [dag.get_vertex_depth(x) for x in gates]
dict_levels     = defaultdict(list)
for inp in inputs:
    dict_levels[0].append(inp)
for key, value in zip(levels,gates):
    dict_levels[key].append(value)
dict_levels = OrderedDict(sorted(dict_levels.items()))

f                = 1.05

#@title Q1-Twall
sol_twall,Twall = solve_twall(dag,gates,inputs,g,p,CL,C_max_pi)

#@title Twall print
print("Twall solution")
print("Twall    =   ",Twall,"*",tau,"ps")
print("Area     =   ",sum(sol_twall["variables"]["x"]))
# print(gates)
# print(sol_1["variables"]["x"])
# print(sol_twall["variables"]["a"])
# print(constraints)

# ctest - 127
# c17 - 6
# c432 - 229
# c880 - 555
# c1908 - 1144
# c2670 - 1958
# c3540 - 2548
# c5315 - 3569
# c6288 - 2672
# c7552 - 5103

#@title Q2-Area Minimisation (continuous)
sol_minarea,Tout = solve_minarea(dag,gates,inputs,g,p,CL,C_max_pi,f,Twall)

#@title Min Area print

# print("Twall solution\\\\")
# print("Twall    =   ",Twall,"*",tau,"ps\\\\")
# print("Area     =   ",sum(sol_minarea["variables"]["x"]),"\\\\\\\\")
print("Min area continuous solution\\\\")
print("f        =   ",f)
print("Tspec    =   ",f*Twall,"*",tau,"ps\\\\")
print("Tout     =   ",Tout,"*",tau,"ps\\\\")
print("Area     =   ",sum(sol_minarea["variables"]["x"]))
# print(gates)
# print(sol_1["variables"]["x"])
# print(sol_2["variables"]["x"])

#@title Q3-Critical path
print("Critical paths for the min area solution")
ai,t0   = dag.calc_ai_t0(sol_minarea["variables"]["x"],gates,CL,g,p)       # fills in timings in the dag
crt_path=dag.find_crt_path()

# @title Q4-Discretisation

print("Discrete sizes solution")
# Assuming all integer values are available

max_gate_size   = 32
min_gate_size   = 1
available_sizes = [x+1 for x in range(0,max_gate_size) ]
Tspec           = f * Twall
N               = len(gates)
Max             = dag.find_max_depth(gates)[0]                      # maximum depth
f_actual        = f

gsize_sol   = [int(round(x)) for x in sol_minarea["variables"]["x"]]
ai,t0       = dag.calc_ai_t0(gsize_sol,gates,CL,g,p)


flag        = 0
if(t0<=Tspec):
    print("round satisfies Tspec")
    flag    =   1                                           # Exit if " round " gives soln satisfying Tspec.

stop = zeros(len(gates),dtype=int)                              # to stop upsizing when cmaxin fails

while t0>Tspec and f>1.01 and flag==0:
    print("current f is ",f)
    level = 1
    changed = zeros(len(gates),dtype=int)

    for level in dict_levels:
        print("at level",level)                                                 # increase gate sizes one by one

        for gate in dict_levels[level]:
            i   = gates.index(gate)
            newz= gsize_sol[i] + adjust_size(level,Max)
            if(newz>=min_gate_size and newz<=max_gate_size):
                gsize_sol[i]  =  newz

            fanin   = dag.get_vertex_fanin(gate)
            fanin_pi= [x for x in fanin if dag.get_vertex_depth(x)==0]

            for j in range(0,len(fanin_pi)):                                  # Cmax_in check
                fanout  = dag.get_vertex_fanout(fanin_pi[j])
                exp     = 0
                for k in fanout:
                    exp = exp + g[gates.index(k)] * gsize_sol[gates.index(k)]
                if(exp>1.02*C_max_pi):
                    print("cmaxin fail. undoing...")
                    gsize_sol[i]  =   gsize_sol[i] - adjust_size(level,Max)    # undo change
                    break

        ai,t0         =   dag.calc_ai_t0(gsize_sol,gates,CL,g,p)        # tspec check
        if(t0<=Tspec):
            flag        =   1
            break

    if(flag==1):
        break

    f                = (f+1)/2                                         # use a false f<current f and solve cont problem. retry for that soln comparing with same Tspec
    sol_minarea_,Tout = solve_minarea(dag,gates,inputs,g,p,CL,C_max_pi,f,Twall)
    gsize_sol        = [int(round(x)) for x in sol_minarea_["variables"]["x"]]
    ai,t0            = dag.calc_ai_t0(gsize_sol,gates,CL,g,p)

    for j in range(0,len(inputs)):                                  # Cmax_in check
        fanout  = dag.get_vertex_fanout(inputs[j])
        exp     = 0
        for k in fanout:
            exp = exp + g[gates.index(k)] * gsize_sol[gates.index(k)]
        if(exp>1.02*C_max_pi):
            print("cmaxin fail after new F-roundoff. exiting...")
            exit(0)

print("Final::")
print("Twall        =   ",Twall,"*",tau,"ps")
print("f            =   ",f_actual)
print("Tspec        =   ",Tspec,"*",tau,"ps")
print("f(false)     =   ",f)
print("Tspec(false) =   ",f*Twall,"*",tau,"ps")
print("Tout         =   ",t0,"*",tau,"ps")
print("Area         =   ",sum(gsize_sol))
print("Twall area   =   ",sum(sol_twall["variables"]["x"]))
print("Min area(cont)=  ",sum(sol_minarea["variables"]["x"]))

#@title Q5-Gate drive strength choices as a cell designer
gt=set(gatetypes)
ni=set(no_inputs)

typ_dict={}                     # dictionary has type and sizes
for x in gt:
    for y in ni:
        typ_dict[(x,y)]=[]

for i in range(len(gates)):
    typ_dict[(gatetypes[i],no_inputs[i])].append(sol_minarea["variables"]["x"][i])

for x in typ_dict:
    try:
        print(x,min(typ_dict[x]),"to",max(typ_dict[x]),len(typ_dict[x]),"\\\\")
    except:
        print(x,"NONE\\\\")

#@title Standard cell  plots
import matplotlib.pyplot as plt

# size range of NOR gate in each circuit
size_NOR = {
    'ctest': [[0,0], [0,0], [0,0]],
    'c17': [[0,0], [0,0], [0,0]],
    'c432': [[1.00, 30.08], [4.07, 4.07], [0,0]],
    'c880': [[1.00, 1.15], [0,0], [0,0]],
    'c1908': [[1.00, 16.69], [1.00, 1.17], [1.00, 1.00]],
    'c2670': [[1.00, 1.17], [1.00, 1.00], [0,0]],
    'c3540': [[1.00, 1.20], [1.00, 1.00], [1.00, 1.00]],
    'c5315': [[1.00, 1.00], [1.00, 7.07], [1.00, 2.14]],
    'c6288': [[1.00, 19.82], [0,0], [0,0]],
    'c7552': [[1.00, 1.35], [1.00, 1.03], [1.00, 1.00]]
}

# No. of NOR gates in each circuit
count_NOR = {
    'ctest': [0, 0, 0],
    'c17': [0, 0, 0],
    'c432': [29, 1, 0],
    'c880': [90, 0, 0],
    'c1908': [18, 7, 5],
    'c2670': [72, 26, 0],
    'c3540': [78, 83, 33],
    'c5315': [133, 66, 63],
    'c6288': [2128, 0, 0],
    'c7552': [274, 43, 34]
}

ABC = ['orange', 'blue', 'green']
NOR_IP = ['NOR2','NOR3','NOR4']

fig = plt.figure(figsize=(12, 8))
ax = fig.add_subplot(111)

bar_width = 0.25
gap_width = 0.5
n_bars = len(size_NOR) * 3
total_width = n_bars * bar_width + (n_bars // 3) * gap_width
ax.set_xlim(-0.5, total_width + 0.5)
tick_positions = [(bar_width + gap_width) * (i // 3) + ((i // 3) * gap_width) + bar_width / 2 for i in range(n_bars)]
tick_labels = [key for key in size_NOR.keys() for _ in range(3)]
ax.set_xticks(tick_positions)
ax.set_xticklabels(tick_labels)

offset = 0
for key, values in size_NOR.items():
    for i, (start, end) in enumerate(values):
        color = ABC[i % 3]
        ax.bar(offset, end - start, bottom=start, width=bar_width, color=color, alpha=0.8)
        ax.text(offset, end + 0.5, count_NOR[key][i], ha='center', va='bottom', color='black')
        offset += bar_width
    offset += gap_width

ax.set_ylabel('size')
ax.set_title('NOR size range for Tspec/Twall = 1.2')
ax.legend(NOR_IP)
plt.tight_layout()
plt.show()

##########################

# size range of NAND gate in each circuit
size_NAND = {
    'ctest': [[0,0], [0,0], [0,0]],
    'c17': [[3.00,30.47], [0,0], [0,0]],
    'c432': [[1.00, 8.96], [2.59, 4.08], [1.00,26.44]],
    'c880': [[1.00, 3.57], [1.00,3.20], [1.00,2.41]],
    'c1908': [[1.00, 18.21], [1.00, 2.16], [1.00, 1.00]],
    'c2670': [[1.00, 6.14], [1.00, 1.76], [1.00,1.24]],
    'c3540': [[1.00, 21.29], [1.00, 1.00], [1.00, 1.00]],
    'c5315': [[1.00, 4.04], [1.00, 1.29], [1.00, 1.00]],
    'c6288': [[1.00, 1.38], [0,0], [0,0]],
    'c7552': [[1.00, 12.51], [1.00, 1.78], [1.00, 1.00]]
}

# No. of NAND gates in each circuit
count_NAND = {
    'ctest': [0, 0, 0],
    'c17': [6, 0, 0],
    'c432': [114, 2, 21],
    'c880': [165, 26, 13],
    'c1908': [391, 15, 10],
    'c2670': [462, 121, 7],
    'c3540': [686, 95, 17],
    'c5315': [790, 364, 31],
    'c6288': [256, 0, 0],
    'c7552': [1597, 153, 74]
}

ABC = ['orange', 'blue', 'green']
NAND_IP = ['NAND2','NAND3','NAND4']

fig = plt.figure(figsize=(12, 8))
ax = fig.add_subplot(111)

bar_width = 0.25
gap_width = 0.5
n_bars = len(size_NAND) * 3
total_width = n_bars * bar_width + (n_bars // 3) * gap_width
ax.set_xlim(-0.5, total_width + 0.5)
tick_positions = [(bar_width + gap_width) * (i // 3) + ((i // 3) * gap_width) + bar_width / 2 for i in range(n_bars)]
tick_labels = [key for key in size_NAND.keys() for _ in range(3)]
ax.set_xticks(tick_positions)
ax.set_xticklabels(tick_labels)

offset = 0
for key, values in size_NAND.items():
    for i, (start, end) in enumerate(values):
        color = ABC[i % 3]
        ax.bar(offset, end - start, bottom=start, width=bar_width, color=color, alpha=0.8)
        ax.text(offset, end + 0.5, count_NAND[key][i], ha='center', va='bottom', color='black')
        offset += bar_width
    offset += gap_width

ax.set_ylabel('size')
ax.set_title('NAND gate size range for Tspec/Twall = 1.2')
ax.legend(NAND_IP)
plt.tight_layout()
plt.show()

##########################

# size range of NOT gate in each circuit
size_NOT = {
    'ctest': [4.26, 32.00],
    'c17': [0, 0],
    'c432': [1.00, 11.88],
    'c880': [1.00, 25.60],
    'c1908': [1.00, 23.61],
    'c2670': [1.00, 30.28],
    'c3540': [1.00, 23.52],
    'c5315': [1.00, 22.65],
    'c6288': [1.00, 2.02],
    'c7552': [1.00, 26.15]
}

# No. of NOT gates in each circuit
count_NOT = {
    'ctest': [127],
    'c17': [0],
    'c432': [62],
    'c880': [261],
    'c1908': [698],
    'c2670': [1270],
    'c3540': [1556],
    'c5315': [2122],
    'c6288': [288],
    'c7552': [2928]
}

x_labels = list(size_NOT.keys())
y_min = [size_NOT[label][0] for label in x_labels]
y_max = [size_NOT[label][1] for label in x_labels]
bar_labels = [count_NOT[label][0] for label in x_labels]

fig, ax = plt.subplots()
ax.bar(x_labels, [y_max[i] - y_min[i] for i in range(len(x_labels))], bottom=y_min, color='green', alpha=0.6, width=0.5, align='center', label='NOT1')
ax.set_ylabel('size')
ax.set_title('NOT gate size range for Tspec/Twall = 1.2')
ax.legend()

for i, v in enumerate(bar_labels):
    ax.text(i, y_max[i] + 0.5, str(v), ha='center')

ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.set_xticks(range(len(x_labels)))
ax.set_xticklabels(x_labels)
ax.set_yticks(range(0, int(max(y_max)) + 2, 5))
plt.xticks(rotation=45, ha='right')
plt.tight_layout()
plt.show()

## These plots show us approximately what standard cell sizes are needed for typical circuits
## Numbers on the bars are no of such gates in the circuits

#@title Q6-Slack calculation**
dag.update_slack(CL,gates,inputs,g,p,gsize_sol,Tspec,dict_levels)

dag.display()

#@title Automated run

circuits = ["ctest","c17","c432","c880","c1908","c2670","c3540","c5315","c6288","c7552"]
# circuits = ["c17"]
fact= [1.05,1.1,1.2,1.3,1.4,1.5]


for ckt in circuits:
        filename = "/content/gdrive/MyDrive/CourseWork/EE6332/netlists/"+ckt+".txt"# Yuk
        # filename = "/content/gdrive/MyDrive/netlists/"+ckt+".txt" #Syam
        module_name, inputs, outputs, wires,gates, gatetypes,no_inputs, dag = parse_verilog_netlist(filename)
        g,p             = calc_g_p(gates,gatetypes)     # Effort calculation
        dag.calc_depths_starter()

        levels          = [dag.get_vertex_depth(x) for x in gates]
        dict_levels     = defaultdict(list)
        for key, value in zip(levels,gates):
            dict_levels[key].append(value)
        dict_levels     = OrderedDict(sorted(dict_levels.items()))

        sol_twall_auto,Twall = solve_twall(dag,gates,inputs,g,p,CL,C_max_pi)

        with open("/content/gdrive/MyDrive/CourseWork/EE6332/netlists/"+ckt+"_results.txt","w") as file:
        # with open("/content/gdrive/MyDrive/netlists/"+ckt+"_results.txt","w") as file:
            file.write("Twall solution\n")
            file.write("Twall    =   "+str(Twall)+"*"+str(tau)+"ps\n")
            file.write("Area     =   "+str(sum(sol_twall_auto["variables"]["x"]))+"\n\n")

            # file.write("Gate size time\n")
            # for i in range(len(gates)):
            #     file.write(gates[i]+"  "+str(sol_twall_auto["variables"]["x"][i])+ " "+str(sol_twall_auto["variables"]["a"][i])+"\n")

            # file.write("\n%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%")
            # file.write("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")

        for f in fact:
            sol_minarea_auto,Tout = solve_minarea(dag,gates,inputs,g,p,CL,C_max_pi,f,Twall)

            with open("/content/gdrive/MyDrive/CourseWork/EE6332/netlists/"+ckt+"_results.txt","a") as file:
            # with open("/content/gdrive/MyDrive/netlists/"+ckt+"_results.txt","a") as file:
                file.write("\n\nMin area solution for Twall/Tspec = "+str(f)+"\n")
                file.write("Tspec    =   "+str(f)+"*"+str(Twall)+"*"+str(tau)+"ps  =  "+str(Tspec)+"*"+str(tau)+"ps\n")
                file.write("Tout     =   "+str(Tout)+"*"+str(tau)+"ps\n")
                file.write("Area     =   "+str(sum(sol_minarea_auto["variables"]["x"]))+"\n\n")

                # file.write("Gate size time\n")
                # for i in range(len(gates)):
                #     file.write(gates[i]+"  "+str(sol_minarea_auto["variables"]["x"][i])+ " "+str(sol_minarea_auto["variables"]["a"][i])+"\n")

                # file.write("\n%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%")
                # file.write("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")

#@title Plots
from numpy import *
from pylab import *

name_circuit = ['c17', 'ctest', 'c432', 'c880', 'c1908', 'c2670', 'c3540', 'c6288', 'c5315', 'c7552']
no_gates_x = [6, 127, 229, 555, 1144, 1958, 2548, 2672, 3569, 5103]
Twall_y = [41.97113, 50.25002, 161.48447, 133.67026, 193.37146, 194.9995, 235.54501, 580.02082, 218.91751, 183.44337]

xlabel('No. of gates')
ylabel('Twall')
title('Twall vs. No. of gates')

for (xi, yi, zi) in zip(no_gates_x, Twall_y, name_circuit):
    plt.text(xi, yi, zi, va='bottom', ha='center')

plot(no_gates_x,Twall_y,'--o',)
show()

TspecTwallratio_x = [1.05,1.1,1.2,1.3,1.4,1.5]
minArea_c2670_y = [3132.26705, 2886.47985, 2697.33785, 2589.16459, 2509.36276, 2446.63154]
minArea_c6288_y = [ 3455.93487, 3139.03531, 2897.00476, 2801.51249, 2755.34247, 2730.43587]

xlabel('Tspec/Twall')
ylabel('min. Area')
xlim(1.0,1.6)
title('For c2670 with Twall (in 5 ps) = 194.99950')
for (xi, yi) in zip(TspecTwallratio_x, minArea_c2670_y):
    plt.text(xi, yi, (xi,yi), va='bottom', ha='center')

plot(TspecTwallratio_x,minArea_c2670_y,'--o',)
show()

xlabel('Tspec/Twall')
ylabel('min. Area')
xlim(1.0,1.6)
title('For c6288 with Twall (in 5 ps) = 580.02082')
for (xi, yi) in zip(TspecTwallratio_x, minArea_c6288_y):
    plt.text(xi, yi, (xi,yi), va='bottom', ha='center')

plot(TspecTwallratio_x,minArea_c6288_y,'--o',)
show()

