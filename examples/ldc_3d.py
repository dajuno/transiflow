import numpy
import pickle

from fvm import Continuation
from fvm import Interface, HYMLSInterface
from fvm import utils

from PyTrilinos import Epetra


class Data:
    def __init__(self):
        self.mu = []
        self.value = []

    def append(self, mu, value):
        self.mu.append(mu)
        self.value.append(value)


def postprocess(data, interface, x, mu, enable_output):
    nx = interface.discretization.nx
    ny = interface.discretization.ny
    nz = interface.discretization.nz

    # Store the solution at every continuation step
    x_local = x.gather()
    if x.Comm().MyPID() == 0 and enable_output:
        data.append(mu, utils.compute_volume_averaged_kinetic_energy(x_local.array, interface))

        with open('ldc_bif_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.obj', 'wb') as f:
            pickle.dump(data, f)

        ke = utils.compute_volume_averaged_kinetic_energy(x_local.array, interface)

        with open('ldc_' + str(mu) + '_ke_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy', 'wb') as f:
            numpy.save(f, ke)

        with open('ldc_' + str(mu) + '_mu_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy', 'wb') as f:
            numpy.save(f, mu)

        with open('ldc_' + str(mu) + '_x_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy', 'wb') as f:
            numpy.save(f, x_local.array)


def main():
    ''' An example of performing a continuation for a 3D lid-driven cavity using HYMLS.
    Multiple processors can be used by calling this script using mpi, e.g.:

    OMP_NUM_THREADS=1 mpiexec -np 4 python examples/ldc_3d.py

    Disabling threading is adviced, since this is broken in Epetra.'''

    dim = 3
    dof = 4
    nx = 16
    ny = nx
    nz = nx

    # Define the problem
    parameters = {'Problem Type': 'Lid-driven Cavity',
                  # Problem parameters
                  'Reynolds Number': 1,
                  'Lid Velocity': 0,
                  # Use a stretched grid
                  'Grid Stretching Factor': 1.5,
                  # Set a maximum step size ds
                  'Maximum Step Size': 100}

    enable_output = False

    # The bordered solver only has to solve one system in each Newton step instead of two.
    # It also can solve a bordered system instead of using projections in the eigenvalue solver.
    # parameters['Bordered Solver'] = True

    # Set some parameters for the Belos solver (GMRES)
    parameters['Solver'] = {}
    parameters['Solver']['Iterative Solver'] = {}
    parameters['Solver']['Iterative Solver']['Maximum Iterations'] = 500
    parameters['Solver']['Iterative Solver']['Num Blocks'] = 100
    parameters['Solver']['Iterative Solver']['Convergence Tolerance'] = 1e-6

    # Use one level in the HYMLS preconditioner. More levels means a less accurate factorization,
    # but more parallelism and a smaller linear system at the coarsest level.
    parameters['Preconditioner'] = {}
    parameters['Preconditioner']['Number of Levels'] = 1

    # Define a communicator that is used to communicate between processors
    comm = Epetra.PyComm()

    # Define a HYMLS interface that handles everything that is different when using HYMLS+Trilinos
    # instead of NumPy as computational backend
    interface = HYMLSInterface.Interface(comm, parameters, nx, ny, nz, dim, dof)
    m = interface.map

    # Because HYMLS uses local subdomains, we need a different interface for postprocessing purposes
    # that operates on the global domain
    postprocess_interface = Interface(interface.parameters,
                                      interface.nx_global, interface.ny_global, interface.nz_global,
                                      interface.discretization.dim, interface.discretization.dof)
    data = Data()
    parameters['Postprocess'] = lambda x, mu: postprocess(data, postprocess_interface, x, mu, enable_output)

    continuation = Continuation(interface, parameters)

    # Compute an initial guess
    x0 = HYMLSInterface.Vector(m)
    x0.PutScalar(0.0)
    x = continuation.continuation(x0, 'Lid Velocity', 0, 1, 1)[0]

    # Perform an initial continuation to Reynolds number 1700 without detecting bifurcation points
    ds = 100
    target = 1800
    parameters['Newton Tolerance'] = 1e-3
    x, mu = continuation.continuation(x0, 'Reynolds Number', 0, target, ds)

    # Store point b from which we start locating the bifurcation point
    x_local = x.gather()
    if comm.MyPID() == 0 and enable_output:
        with open('ldc_b_mu_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy', 'wb') as f:
            numpy.save(f, mu)

        with open('ldc_b_x_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy', 'wb') as f:
            numpy.save(f, x_local.array)

    # # Restart from point b. In this case the above code can be disabled
    # interface.set_parameter('Lid Velocity', 1)
    # mu = numpy.load('ldc_b_mu_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy')
    # if comm.MyPID() == 0:
    #     x = numpy.load('ldc_b_x_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy')
    # else:
    #     x = []

    # x = HYMLSInterface.Vector.from_array(m, x)

    # Now detect the bifurcation point
    parameters['Newton Tolerance'] = 1e-6
    parameters['Destination Tolerance'] = 1e-4
    parameters['Detect Bifurcation Points'] = True
    parameters['Maximum Step Size'] = 100

    parameters['Eigenvalue Solver'] = {}
    parameters['Eigenvalue Solver']['Target'] = 0.4j
    parameters['Eigenvalue Solver']['Tolerance'] = 1e-8
    parameters['Eigenvalue Solver']['Number of Eigenvalues'] = 2

    ds = 100
    target = 2500
    x2, mu2 = continuation.continuation(x, 'Reynolds Number', mu, target, ds)

    # Store the solution at the bifurcation point
    x_local = x2.gather()
    if comm.MyPID() == 0 and enable_output:
        ke = utils.compute_volume_averaged_kinetic_energy(x_local.array, interface)

        with open('ldc_c_ke_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy', 'wb') as f:
            numpy.save(f, ke)

        with open('ldc_c_mu_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy', 'wb') as f:
            numpy.save(f, mu2)

        with open('ldc_c_x_' + str(nx) + '_' + str(ny) + '_' + str(nz) + '.npy', 'wb') as f:
            numpy.save(f, x_local.array)


if __name__ == '__main__':
    main()
