from __future__ import print_function

# standard library imports
import sys
from os import path
try:
    from io import StringIO
except:
    from StringIO import StringIO

# third party
import numpy as np
from scipy.optimize.lbfgsb import LbfgsInvHessProduct

# local application imports
from ._linesearch import backtrack,NoLineSearch
from .base_optimizer import base_optimizer
from utilities import *

class iterationData:
    """docstring for iterationData"""
    def __init__(self, alpha, s, y):
        self.alpha = alpha
        self.s_prim = s  #step
        self.y_prim = y  #diff in grad 

class lbfgs(base_optimizer):
    """the class of lbfgs method"""
       
    def __init__(self,options):
        super(lbfgs,self).__init__(options)
        self.k = 0
        self.end = 0

    def optimize(
            self,
            molecule,
            refE=0.,
            opt_type='UNCONSTRAINED',
            opt_steps=20,
            maxcor=10,
            ictan=None,
            xyzframerate=4,
            ):

        # stash/initialize some useful attributes
        print(" initial E %5.4f" % (molecule.energy - refE))
        geoms = []
        energies=[]
        geoms.append(molecule.geometry)
        energies.append(molecule.energy-refE)
        self.disp = 1000.
        self.Ediff = 1000.
        self.check_inputs(molecule,opt_type,ictan)
        nconstraints=self.get_nconstraints(opt_type)
        self.buf = StringIO()

        # form initial coord basis
        constraints = self.get_constraint_vectors(molecule,opt_type,ictan)
        molecule.update_coordinate_basis(constraints=constraints)

        # get coordinates 
        x = np.copy(molecule.coordinates)
        xyz = np.copy(molecule.xyz)
        x_prim = molecule.primitive_internal_values
        num_coords =  molecule.num_coordinates - nconstraints 
        
        # Evaluate the function value and its gradient.
        fx = molecule.energy
        g = molecule.gradient.copy()
    
        # project out the constraint
        gc = g - np.dot(g.T,molecule.constraints)*molecule.constraints

        g_prim = block_matrix.dot(molecule.coord_basis,gc)
        molecule.gradrms = np.sqrt(np.dot(gc.T,gc)/num_coords)

        if molecule.gradrms < self.conv_grms:
            print(" already at min")
            return geoms,energies 
        
        # reset k in principle k does not have to reset but . . . 
        #self.k = 0
        #self.end=0

        # initialize the iteration data list
        if self.k==0:
            self.lm = []
            for i in xrange(0, maxcor):
                s_prim = np.zeros_like(g_prim)
                y_prim = np.zeros_like(g_prim)
                self.lm.append(iterationData(0.0, s_prim.flatten(), y_prim.flatten()))
       
        for ostep in range(opt_steps):
            print(" On opt step {} ".format(ostep+1))

            if self.k!=0:
                # update vectors s and y:
                self.lm[self.end].s_prim = molecule.coord_obj.Prims.calcDiff(xyz,self.xyzp)
                self.lm[self.end].y_prim = g_prim - self.gp_prim
                self.end = (self.end + 1) % maxcor
                #j = self.end
                bound = min(self.k, maxcor)
                s_prim = np.array([self.lm[i].s_prim.flatten() for i in xrange(maxcor)])
                y_prim = np.array([self.lm[i].y_prim.flatten() for i in xrange(maxcor)])
                hess_inv = LbfgsInvHessProduct(s_prim[:bound],y_prim[:bound])
                # compute the negative gradients
                d_prim = -g_prim
                # perform matrix product
                d_prim = hess_inv._matvec(d_prim)
                d_prim = np.reshape(d_prim,(-1,1))
            else:
                # d: store the negative gradient of the object function on point x.
                d_prim = -g_prim
            self.k = self.k + 1

            # form in DLC basis (does nothing if cartesian)
            d = block_matrix.dot(block_matrix.transpose(molecule.coord_basis),d_prim)

            # normalize the direction
            actual_step = np.linalg.norm(d)
            print(" actual_step= %1.2f"% actual_step)
            d = d/actual_step #normalize
            if actual_step>self.options['DMAX']:
                step=self.options['DMAX']
                print(" reducing step, new step = %1.2f" %step)
            else:
                step=actual_step

            # store
            xp = x.copy()
            self.xyzp = xyz.copy()
            gp = gc.copy()
            self.gp_prim = block_matrix.dot(molecule.coord_basis,gp)
            fxp = fx

            # => calculate constraint step <= #
            constraint_steps = self.get_constraint_steps(molecule,opt_type,g)

            # line search  
            #print(" Linesearch")
            ls = self.Linesearch(nconstraints, x, fx, gc, d, step, xp, gp,constraint_steps,self.linesearch_parameters,molecule)
            #print(" Done linesearch")
            
            # revert to the privious point
            if ls['status'] < 0:
                x = xp.copy()
                g = gp.copy()
                print('[ERROR] the point return to the previous point')
                return ls['status']

            # save new values from linesearch
            step = ls['step']
            x = ls['x']
            fx = ls['fx']
            g  = ls['g']
            gc = g - np.dot(g.T,molecule.constraints)*molecule.constraints
            g_prim = block_matrix.dot(molecule.coord_basis,gc)
            dEstep = fx - fxp
            print(" dEstep=%5.4f" %dEstep)
            dE = molecule.difference_energy
            if dE is not 1000.:
                print(" difference energy is %5.4f" % dE)
            molecule.gradrms = np.sqrt(np.dot(gc.T,gc)/num_coords)

            # update molecule xyz
            xyz = molecule.update_xyz(x-xp)

            if ostep % xyzframerate==0:
                geoms.append(molecule.geometry)
                energies.append(molecule.energy-refE)

            if self.options['print_level']>0:
                print(" Opt step: %d E: %5.4f gradrms: %1.5f ss: %1.3f DMAX: %1.3f" % (ostep+1,fx-refE,molecule.gradrms,step,self.options['DMAX']))
            self.buf.write(u' Opt step: %d E: %5.4f gradrms: %1.5f ss: %1.3f DMAX: %1.3f\n' % (ostep+1,fx-refE,molecule.gradrms,step,self.options['DMAX']))

            # check for convergence TODO
            if molecule.gradrms < self.conv_grms:
                print(" Converged! gradrms: %.4f" % molecule.gradrms) 
                if ostep % xyzframerate!=0:
                    geoms.append(molecule.geometry)
                    energies.append(molecule.energy-refE)
                break

            #print " ########## DONE WITH TOTAL STEP #########"


        print(" opt-summary")
        print(self.buf.getvalue())
        return geoms,energies
