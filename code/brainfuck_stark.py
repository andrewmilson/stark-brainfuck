from fri import *
from instruction_extension import InstructionExtension
from memory_extension import MemoryExtension
from processor_extension import ProcessorExtension
from io_extension import IOExtension
from univariate import *
from multivariate import *
from ntt import *
from functools import reduce
import os

from vm import VirtualMachine


class BrainfuckStark:
    def __init__(self):
        # set parameters
        self.field = BaseField.main()
        self.expansion_factor = 16
        self.num_colinearity_checks = 40
        self.security_level = 160
        assert(self.expansion_factor & (self.expansion_factor - 1)
               == 0), "expansion factor must be a power of 2"
        assert(self.expansion_factor >=
               4), "expansion factor must be 4 or greater"
        assert(self.num_colinearity_checks * len(bin(self.expansion_factor)
               [3:]) >= self.security_level), "number of colinearity checks times log of expansion factor must be at least security level"

        self.num_randomizers = 4*self.num_colinearity_checks

        self.vm = VirtualMachine()

    def transition_degree_bounds(self, transition_constraints):
        point_degrees = [1] + [self.original_trace_length +
                               self.num_randomizers-1] * 2*self.num_registers
        return [max(sum(r*l for r, l in zip(point_degrees, k)) for k, v in a.dictionary.items()) for a in transition_constraints]

    def transition_quotient_degree_bounds(self, transition_constraints):
        return [d - (self.original_trace_length-1) for d in self.transition_degree_bounds(transition_constraints)]

    def max_degree(self, transition_constraints):
        md = max(self.transition_quotient_degree_bounds(transition_constraints))
        return (1 << (len(bin(md)[2:]))) - 1

    def boundary_zerofiers(self, boundary):
        zerofiers = []
        for s in range(self.num_registers):
            points = [self.omicron ^ c for c, r, v in boundary if r == s]
            zerofiers = zerofiers + [Polynomial.zerofier_domain(points)]
        return zerofiers

    def boundary_interpolants(self, boundary):
        interpolants = []
        for s in range(self.num_registers):
            points = [(c, v) for c, r, v in boundary if r == s]
            domain = [self.omicron ^ c for c, v in points]
            values = [v for c, v in points]
            interpolants = interpolants + \
                [Polynomial.interpolate_domain(domain, values)]
        return interpolants

    def boundary_quotient_degree_bounds(self, randomized_trace_length, boundary):
        randomized_trace_degree = randomized_trace_length - 1
        return [randomized_trace_degree - bz.degree() for bz in self.boundary_zerofiers(boundary)]

    def sample_weights(self, number, randomness):
        return [self.field.sample(blake2b(randomness + bytes(i)).digest()) for i in range(0, number)]

    @staticmethod
    def roundup_npo2(integer):
        if integer == 0 or integer == 1:
            return 1
        return 1 << (len(bin(integer-1)[2:]))

    def prove(self, processor_table, instruction_table, memory_table, input_table, output_table, proof_stream=None):
        # infer details about computation
        original_trace_length = len(processor_table.table)
        rounded_trace_length = BrainfuckStark.roundup_npo2(
            original_trace_length)
        randomized_trace_length = rounded_trace_length + self.num_randomizers

        # compute fri domain length
        air_degree = 8  # TODO verify me
        tp_degree = air_degree * (randomized_trace_length - 1)
        tq_degree = tp_degree - (rounded_trace_length - 1)
        tqd_roundup = BrainfuckStark.roundup_npo2(
            tq_degree + 1) - 1  # The max degree bound provable by FRIcal
        fri_domain_length = (tqd_roundup+1) * self.expansion_factor

        # compute generators
        generator = self.field.generator()
        omega = self.field.primitive_nth_root(fri_domain_length)
        omicron = self.field.primitive_nth_root(
            rounded_trace_length)

        # check numbers for sanity
        # print(original_trace_length)
        # print(rounded_trace_length)
        # print(randomized_trace_length)
        # print(air_degree)
        # print(tp_degree)
        # print(tq_degree)
        # print(tqd_roundup)
        # print(fri_domain_length)

        # instantiate helper objects
        fri = Fri(generator, omega, fri_domain_length,
                  self.expansion_factor, self.num_colinearity_checks)

        if proof_stream == None:
            proof_stream = ProofStream()

        # apply randomizers and interpolate
        randomizer_coset = [(self.generator ^ 2) * (self.omega ^ i)
                            for i in range(0, self.num_randomizers)]
        omicron_domain = [self.omicron ^
                          i for i in range(rounded_trace_length)]
        processor_polynomials = processor_table.interpolate(
            self.generator ^ 2, self.omicron, rounded_trace_length, self.num_randomizers)
        instruction_polynomials = instruction_table.interpolate(
            self.generator ^ 2, self.omicron, rounded_trace_length, self.num_randomizers)
        memory_polynomials = memory_table.interpolate(
            self.generator ^ 2, self.omicron, rounded_trace_length, self.num_randomizers)
        input_polynomials = input_table.interpolate(
            self.generator ^ 2, self.omicron, rounded_trace_length, self.num_randomizers)
        output_polynomials = output_table.interpolate(
            self.generator ^ 2, self.omicron, rounded_trace_length, self.num_randomizers)

        # commit
        base_root = fri.batch_commit(
            processor_polynomials + instruction_polynomials + memory_polynomials + input_polynomials + output_polynomials)
        proof_stream.push(base_root)

        # get coefficients for table extensions
        a, b, c, d, e, f, alpha, beta, gamma, delta, eta = proof_stream.prover_fiat_shamir(
            num_bytes=self.vm.num_challenges() * 3 * 9)

        # extend tables
        processor_extension = ProcessorExtension.extend(
            processor_table, a, b, c, d, e, f, alpha, beta, gamma, delta)
        instruction_extension = InstructionExtension.extend(
            instruction_table, a, b, c, alpha, eta)
        memory_extension = MemoryExtension.extend(memory_table, d, e, f, beta)
        input_extension = IOExtension.extend(input_table, gamma)
        output_extension = IOExtension.extend(output_table, delta)

        # get terminal values
        processor_instruction_permutation_terminal = processor_extension.instruction_permutation_terminal
        processor_memory_permutation_terminal = processor_extension.memory_permutation_terminal
        processor_input_evaluation_terminal = processor_extension.input_evaluation_terminal
        processor_output_evaluation_terminal = processor_extension.output_evaluation_terminal
        instruction_evaluation_terminal = instruction_extension.evaluation_terminal

        # send terminals
        proof_stream.push(processor_instruction_permutation_terminal)
        proof_stream.push(processor_memory_permutation_terminal)
        proof_stream.push(processor_input_evaluation_terminal)
        proof_stream.push(processor_output_evaluation_terminal)
        proof_stream.push(instruction_evaluation_terminal)

        # interpolate extension columns
        processor_extension_polynomials = processor_extension.interpolate_extension(
            self.generator ^ 2, omicron, rounded_trace_length, self.num_randomizers)
        instruction_extension_polynomials = instruction_extension.interpolate_extension(
            self.generator ^ 2, omicron, rounded_trace_length, self.num_randomizers)
        memory_extension_polynomials = memory_extension.interpolate_extension(
            self.generator ^ 2, omicron, rounded_trace_length, self.num_randomizers)
        input_extension_polynomials = input_extension.interpolate_extension(
            self.generator ^ 2, omicron, rounded_trace_length, self.num_randomizers)
        output_extension_polynomials = output_extension.interpolate_extension(
            self.generator ^ 2, omicron, rounded_trace_length, self.num_randomizers)

        # commit to extension polynomials
        extension_root = fri.batch_commit(processor_extension_polynomials + instruction_extension_polynomials +
                                          memory_extension_polynomials + input_extension_polynomials + output_extension_polynomials)
        proof_stream.push(extension_root)

        # gather polynomials derived from generalized AIR constraints relating to ...
        polynomials = []
        # ... boundary ...
        polynomials += processor_extension.boundary_quotients()
        polynomials += instruction_extension.boundary_quotients()
        polynomials += memory_extension.boundary_quotients()
        polynomials += input_extension.boundary_quotients()
        polynomials += output_extension.boundary_quotients()
        # ... transitions ...
        polynomials += processor_extension.transition_quotients()
        polynomials += instruction_extension.transition_quotients()
        polynomials += memory_extension.transition_quotients()
        polynomials += input_extension.transition_quotients()
        polynomials += output_extension.transition_quotients()
        # ... terminal values ...
        polynomials += processor_extension.terminal_quotients()
        polynomials += instruction_extension.terminal_quotients()
        polynomials += memory_extension.terminal_quotients()
        polynomials += input_extension.terminal_quotients()
        polynomials += output_extension.terminal_quotients()
        # ... and equal initial values
        polynomials += (processor_extension_polynomials[0] -
                        instruction_extension_polynomials[0]) / (X - omicron)
        polynomials += (processor_extension_polynomials[1] -
                        memory_extension_polynomials[0]) / (X - omicron)

        # subtract boundary interpolants and divide out boundary zerofiers
        boundary_quotients = []
        for s in range(self.num_registers):
            interpolant = self.boundary_interpolants(boundary)[s]
            zerofier = self.boundary_zerofiers(boundary)[s]
            quotient = (trace_polynomials[s] - interpolant) / zerofier
            boundary_quotients += [quotient]

        # commit to boundary quotients
        boundary_quotient_codewords = []
        boundary_quotient_Merkle_roots = []
        for s in range(self.num_registers):
            boundary_quotient_codewords = boundary_quotient_codewords + \
                [fast_coset_evaluate(
                    boundary_quotients[s], self.generator, self.omega, self.fri_domain_length)]
            merkle_root = Merkle.commit(boundary_quotient_codewords[s])
            proof_stream.push(merkle_root)

        # symbolically evaluate transition constraints
        point = [Polynomial([self.field.zero(), self.field.one(
        )])] + trace_polynomials + [tp.scale(self.omicron) for tp in trace_polynomials]
        transition_polynomials = [a.evaluate_symbolic(
            point) for a in transition_constraints]

        # divide out zerofier
        transition_quotients = [fast_coset_divide(
            tp, transition_zerofier, self.generator, self.omicron, self.omicron_domain_length) for tp in transition_polynomials]

        # commit to randomizer polynomial
        randomizer_polynomial = Polynomial([self.field.sample(os.urandom(
            17)) for i in range(self.max_degree(transition_constraints)+1)])
        randomizer_codeword = fast_coset_evaluate(
            randomizer_polynomial, self.generator, self.omega, self.fri_domain_length)
        randomizer_root = Merkle.commit(randomizer_codeword)
        proof_stream.push(randomizer_root)

        # get weights for nonlinear combination
        #  - 1 randomizer
        #  - 2 for every transition quotient
        #  - 2 for every boundary quotient
        weights = self.sample_weights(1 + 2*len(transition_quotients) + 2*len(
            boundary_quotients), proof_stream.prover_fiat_shamir())

        assert([tq.degree() for tq in transition_quotients] == self.transition_quotient_degree_bounds(
            transition_constraints)), "transition quotient degrees do not match with expectation"

        # compute terms of nonlinear combination polynomial
        x = Polynomial([self.field.zero(), self.field.one()])
        max_degree = self.max_degree(transition_constraints)
        terms = []
        terms += [randomizer_polynomial]
        for i in range(len(transition_quotients)):
            terms += [transition_quotients[i]]
            shift = max_degree - \
                self.transition_quotient_degree_bounds(
                    transition_constraints)[i]
            terms += [(x ^ shift) * transition_quotients[i]]
        for i in range(self.num_registers):
            terms += [boundary_quotients[i]]
            shift = max_degree - \
                self.boundary_quotient_degree_bounds(len(trace), boundary)[i]
            terms += [(x ^ shift) * boundary_quotients[i]]

        # take weighted sum
        # combination = sum(weights[i] * terms[i] for all i)
        combination = reduce(
            lambda a, b: a+b, [Polynomial([weights[i]]) * terms[i] for i in range(len(terms))], Polynomial([]))

        # compute matching codeword
        combined_codeword = fast_coset_evaluate(
            combination, self.generator, self.omega, self.fri_domain_length)

        # prove low degree of combination polynomial, and collect indices
        indices = self.fri.prove(combined_codeword, proof_stream)

        # process indices
        duplicated_indices = [i for i in indices] + \
            [(i + self.expansion_factor) %
             self.fri.domain_length for i in indices]
        quadrupled_indices = [i for i in duplicated_indices] + [
            (i + (self.fri.domain_length // 2)) % self.fri.domain_length for i in duplicated_indices]
        quadrupled_indices.sort()

        # open indicated positions in the boundary quotient codewords
        for bqc in boundary_quotient_codewords:
            for i in quadrupled_indices:
                proof_stream.push(bqc[i])
                path = Merkle.open(i, bqc)
                proof_stream.push(path)

        # ... as well as in the randomizer
        for i in quadrupled_indices:
            proof_stream.push(randomizer_codeword[i])
            path = Merkle.open(i, randomizer_codeword)
            proof_stream.push(path)

        # ... and also in the zerofier!
        for i in quadrupled_indices:
            proof_stream.push(transition_zerofier_codeword[i])
            path = Merkle.open(i, transition_zerofier_codeword)
            proof_stream.push(path)

        # the final proof is just the serialized stream
        return proof_stream.serialize()

    def verify(self, proof, transition_constraints, boundary, transition_zerofier_root, proof_stream=None):
        H = blake2b

        # infer trace length from boundary conditions
        original_trace_length = 1 + max(c for c, r, v in boundary)
        randomized_trace_length = original_trace_length + self.num_randomizers

        # deserialize with right proof stream
        if proof_stream == None:
            proof_stream = ProofStream()
        proof_stream = proof_stream.deserialize(proof)

        # get Merkle roots of boundary quotient codewords
        boundary_quotient_roots = []
        for s in range(self.num_registers):
            boundary_quotient_roots = boundary_quotient_roots + \
                [proof_stream.pull()]

        # get Merkle root of randomizer polynomial
        randomizer_root = proof_stream.pull()

        # get weights for nonlinear combination
        weights = self.sample_weights(1 + 2*len(transition_constraints) + 2*len(
            self.boundary_interpolants(boundary)), proof_stream.verifier_fiat_shamir())

        # verify low degree of combination polynomial
        polynomial_values = []
        verifier_accepts = self.fri.verify(proof_stream, polynomial_values)
        polynomial_values.sort(key=lambda iv: iv[0])
        if not verifier_accepts:
            return False

        indices = [i for i, v in polynomial_values]
        values = [v for i, v in polynomial_values]

        # read and verify leafs, which are elements of boundary quotient codewords
        duplicated_indices = [i for i in indices] + \
            [(i + self.expansion_factor) %
             self.fri.domain_length for i in indices]
        duplicated_indices.sort()
        leafs = []
        for r in range(len(boundary_quotient_roots)):
            leafs = leafs + [dict()]
            for i in duplicated_indices:
                leafs[r][i] = proof_stream.pull()
                path = proof_stream.pull()
                verifier_accepts = verifier_accepts and Merkle.verify(
                    boundary_quotient_roots[r], i, path, leafs[r][i])
                if not verifier_accepts:
                    return False

        # read and verify randomizer leafs
        randomizer = dict()
        for i in duplicated_indices:
            randomizer[i] = proof_stream.pull()
            path = proof_stream.pull()
            verifier_accepts = verifier_accepts and Merkle.verify(
                randomizer_root, i, path, randomizer[i])
            if not verifier_accepts:
                return False

        # read and verify transition zerofier leafs
        transition_zerofier = dict()
        for i in duplicated_indices:
            transition_zerofier[i] = proof_stream.pull()
            path = proof_stream.pull()
            verifier_accepts = verifier_accepts and Merkle.verify(
                transition_zerofier_root, i, path, transition_zerofier[i])
            if not verifier_accepts:
                return False

        # verify leafs of combination polynomial
        for i in range(len(indices)):
            current_index = indices[i]  # do need i

            # get trace values by applying a correction to the boundary quotient values (which are the leafs)
            domain_current_index = self.generator * \
                (self.omega ^ current_index)
            next_index = (current_index +
                          self.expansion_factor) % self.fri.domain_length
            domain_next_index = self.generator * (self.omega ^ next_index)
            current_trace = [self.field.zero()
                             for s in range(self.num_registers)]
            next_trace = [self.field.zero() for s in range(self.num_registers)]
            for s in range(self.num_registers):
                zerofier = self.boundary_zerofiers(boundary)[s]
                interpolant = self.boundary_interpolants(boundary)[s]

                current_trace[s] = leafs[s][current_index] * zerofier.evaluate(
                    domain_current_index) + interpolant.evaluate(domain_current_index)
                next_trace[s] = leafs[s][next_index] * zerofier.evaluate(
                    domain_next_index) + interpolant.evaluate(domain_next_index)

            point = [domain_current_index] + current_trace + next_trace
            transition_constraints_values = [transition_constraints[s].evaluate(
                point) for s in range(len(transition_constraints))]

            # compute nonlinear combination
            counter = 0
            terms = []
            terms += [randomizer[current_index]]
            for s in range(len(transition_constraints_values)):
                tcv = transition_constraints_values[s]
                quotient = tcv / transition_zerofier[current_index]
                terms += [quotient]
                shift = self.max_degree(
                    transition_constraints) - self.transition_quotient_degree_bounds(transition_constraints)[s]
                terms += [quotient * (domain_current_index ^ shift)]
            for s in range(self.num_registers):
                bqv = leafs[s][current_index]  # boundary quotient value
                terms += [bqv]
                shift = self.max_degree(
                    transition_constraints) - self.boundary_quotient_degree_bounds(randomized_trace_length, boundary)[s]
                terms += [bqv * (domain_current_index ^ shift)]
            combination = reduce(
                lambda a, b: a+b, [terms[j] * weights[j] for j in range(len(terms))], self.field.zero())

            # verify against combination polynomial value
            verifier_accepts = verifier_accepts and (combination == values[i])
            if not verifier_accepts:
                return False

        return verifier_accepts
