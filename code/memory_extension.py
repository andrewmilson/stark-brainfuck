from re import M, T
from memory_table import *
from table_extension import TableExtension


class MemoryExtension(TableExtension):
    # name columns
    cycle = 0
    memory_pointer = 1
    memory_value = 2

    permutation = 3

    width = 4

    def __init__(self, length, num_randomizers, generator, order, d, e, f, beta, permutation_terminal):
        super(MemoryExtension, self).__init__(
            d.field, 3, MemoryExtension.width, length, num_randomizers, generator, order)

        # terminal values
        self.permutation_terminal = permutation_terminal
        self.terminals = [permutation_terminal]

        self.d = MPolynomial.constant(d)
        self.e = MPolynomial.constant(e)
        self.f = MPolynomial.constant(f)
        self.beta = MPolynomial.constant(beta)
        self.challenges = [d, e, f, beta]

    @staticmethod
    def prepare_verify(log_num_rows, challenges, terminals):
        d, e, f, beta = challenges
        memory_extension = MemoryExtension(d, e, f, beta)
        memory_extension.permutation_terminal = terminals[0]
        memory_extension.log_num_rows = log_num_rows
        memory_extension.terminals = terminals
        return memory_extension

    @staticmethod
    def extend(memory_table, all_challenges, all_initials):
        a, b, c, d, e, f, alpha, beta, gamma, delta, eta = all_challenges
        processor_instruction_permutation_initial, processor_memory_permutation_initial = all_initials

        # algebra stuff
        field = memory_table.field
        xfield = d.field
        one = xfield.one()

        # prepare loop
        extended_matrix = []
        memory_permutation_running_product = processor_memory_permutation_initial

        # loop over all rows of table
        for i in range(len(memory_table.matrix)):
            row = memory_table.matrix[i]
            new_row = [xfield.lift(nr) for nr in row]

            new_row += [memory_permutation_running_product]
            memory_permutation_running_product *= beta \
                - d * new_row[MemoryExtension.cycle] \
                - e * new_row[MemoryExtension.memory_pointer] \
                - f * new_row[MemoryExtension.memory_value]

            extended_matrix += [new_row]

        memory_table.matrix = extended_matrix
        memory_table.field = xfield
        memory_table.codewords = [[xfield.lift(c) for c in cdwd] for cdwd in memory_table.codewords]
        # memory_table.initials = all_initials
        # memory_table.challenges = all_challenges

        extended_memory_table = MemoryExtension(
            memory_table.length, memory_table.num_randomizers, memory_table.generator, memory_table.order, d, e, f, beta, memory_permutation_running_product)
        extended_memory_table.matrix = extended_matrix

        extended_memory_table.field = xfield

        extended_memory_table.polynomials = memory_table.polynomials
        extended_memory_table.codewords = [
            [xfield.lift(c) for c in cdwd] for cdwd in memory_table.codewords]

        return extended_memory_table

    def transition_constraints_ext(self, challenges):
        d, e, f, beta = [MPolynomial.constant(c) for c in challenges]
        cycle, address, value, permutation, \
            cycle_next, address_next, value_next, permutation_next = MPolynomial.variables(
                8, self.field)

        polynomials = MemoryTable.transition_constraints_afo_named_variables(
            cycle, address, value, cycle_next, address_next, value_next)

        assert(len(polynomials) ==
               3), f"number of transition constraints from MemoryTable is {len(polynomials)}, but expected 3"

        polynomials += [permutation *
                        (beta - d * cycle
                         - e * address
                         - f * value)
                        - permutation_next]

        return polynomials

    def boundary_constraints_ext(self):
        # format: mpolynomial
        x = MPolynomial.variables(self.width, self.field)
        one = MPolynomial.constant(self.field.one())
        zero = MPolynomial.zero()
        return [x[MemoryExtension.cycle] - zero,  # cycle
                x[MemoryExtension.memory_pointer] - zero,  # memory pointer
                x[MemoryExtension.memory_value] - zero,  # memory value
                # x[MemoryExtension.permutation] - one   # permutation
                ]

    def terminal_constraints_ext(self, challenges, terminals):
        d, e, f, beta = [MPolynomial.constant(c) for c in challenges]
        permutation = terminals[0]
        x = MPolynomial.variables(self.width, self.field)

        # [permutation *
        #                 (beta - d * cycle
        #                  - e * address
        #                  - f * value)
        #                 - permutation_next]

        return [x[MemoryExtension.permutation] * (beta - d * x[MemoryTable.cycle] - e * x[MemoryTable.memory_pointer] - f * x[MemoryTable.memory_value]) - MPolynomial.constant(permutation)]
