#Copyright (C) 2011 Robert Lanfear and Brett Calcott
#
#This program is free software: you can redistribute it and/or modify it
#under the terms of the GNU General Public License as published by the
#Free Software Foundation, either version 3 of the License, or (at your
#option) any later version.
#
#This program is distributed in the hope that it will be useful, but
#WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#General Public License for more details. You should have received a copy
#of the GNU General Public License along with this program.  If not, see
#<http://www.gnu.org/licenses/>. PartitionFinder also includes the PhyML
#program and the PyParsing library both of which are protected by their
#own licenses and conditions, using PartitionFinder implies that you
#agree with those licences and conditions as well.

"""Run raxml and parse the output"""

import logging
log = logging.getLogger("analysis")

import subprocess, shlex, os, shutil, sys, fnmatch

from pyparsing import (
    Word, Literal, nums, Suppress, ParseException,
    SkipTo,
    )

from raxml_models import get_model_commandline

_binary_name = 'raxml'
if sys.platform == 'win32':
    _binary_name += ".exe"

from util import PhylogenyProgramError
class RaxmlError(PhylogenyProgramError):
    pass

def find_program():
    """Locate the binary ..."""
    pth = os.path.abspath(__file__)

    # Split off the name and the directory...
    pth, notused = os.path.split(pth)
    pth, notused = os.path.split(pth)
    pth = os.path.join(pth, "programs", _binary_name)
    pth = os.path.normpath(pth)

    log.debug("Checking for program %s", _binary_name)
    if not os.path.exists(pth) or not os.path.isfile(pth):
        log.error("No such file: '%s'", pth)
        raise RaxmlError
    log.debug("Found program %s at '%s'", _binary_name, pth)
    return pth

_raxml_binary = None
def run_raxml(command):
    global _raxml_binary
    if _raxml_binary is None:
        _raxml_binary = find_program()

    # Add in the command file
    log.debug("Running 'raxml %s'", command)
    command = "\"%s\" %s" % (_raxml_binary, command)

    # Note: We use shlex.split as it does a proper job of handling command
    # lines that are complex
    p = subprocess.Popen(
        shlex.split(command),
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)

    # Capture the output, we might put it into the errors
    stdout, stderr = p.communicate()
    # p.terminate()

    if p.returncode != 0:
        log.error("RAxML did not execute successfully")
        log.error("RAxML output follows, in case it's helpful for finding the problem")
        log.error("%s", stdout)
        log.error("%s", stderr)
        raise RaxmlError

def dupfile(src, dst):
    # Make a copy or a symlink so that we don't overwrite different model runs
    # of the same alignment

    # TODO maybe this should throw...?
    try:
        if os.path.exists(dst):
            os.remove(dst)
        shutil.copyfile(src, dst)
    except OSError:
        log.error("Cannot link/copy file %s to %s", src, dst)
        raise RaxmlError

def make_topology(alignment_path, datatype):
    '''Make a MP tree to start the analysis'''
    log.info("Making MP tree for %s", alignment_path)

    # First get the MP topology like this (-p is a hard-coded random number seed):
    if datatype=="DNA":
        command = "-y -s '%s' -m GTRGAMMA -n MPTREE -p 123456789" % (alignment_path)
    elif datatype=="protein":
        command = "-y -s '%s' -m PROTGAMMALG -n MPTREE -p 123456789" % (alignment_path)
    else:
        log.error("Unrecognised datatype: '%s'" % (datatype))
        raise(RaxmlError)

    #force raxml to write to the dir with the alignment in it
    aln_dir, fname = os.path.split(alignment_path)
    command = ''.join([command, " -w '%s'" % os.path.abspath(aln_dir)])

    run_raxml(command)
    dir, aln = os.path.split(alignment_path)
    tree_path = os.path.join(dir, "RAxML_parsimonyTree.MPTREE")
    return tree_path

def make_branch_lengths(alignment_path, topology_path, datatype):
    #Now we re-estimate branchlengths using a GTR+G model on the (unpartitioned) dataset
    dir_path, fname = os.path.split(topology_path)
    tree_path = os.path.join(dir_path, 'topology_tree.phy')
    log.debug("Copying %s to %s", topology_path, tree_path)
    dupfile(topology_path, tree_path)

    if datatype=="DNA":
        log.info("Estimating GTR+G branch lengths on tree using RAxML")
        command = "-f e -s '%s' -t '%s' -m GTRGAMMA -n BLTREE -w '%s'" % (
            alignment_path, tree_path, os.path.abspath(dir_path))
        run_raxml(command)
    if datatype=="protein":
        log.info("Estimating LG+G branch lengths on tree using RAxML")
        command = "-f e -s '%s' -t '%s' -m PROTGAMMALG -n BLTREE -w '%s'" % (
            alignment_path, tree_path, os.path.abspath(dir_path))
        run_raxml(command)

    dir, aln = os.path.split(alignment_path)
    tree_path = os.path.join(dir, "RAxML_result.BLTREE")
    log.info("Branchlength estimation finished")

    # Now return the path of the final tree with branch lengths
    return tree_path

def analyse(model, alignment_path, tree_path, branchlengths):
    """Do the analysis -- this will overwrite stuff!"""

    # Move it to a new name to stop raxml stomping on different model analyses
    # dupfile(alignment_path, analysis_path)
    model_params = get_model_commandline(model)

    if branchlengths == 'linked':
        #constrain all branchlengths to be equal
        bl = ' -f B '
    elif branchlengths == 'unlinked':
        #let branchlenghts vary among subsets
        bl = ' -f e '
    else:
        # WTF?
        log.error("Unknown option for branchlengths: %s", branchlengths)
        raise RaxmlError

    #raxml doesn't append alignment names automatically, like PhyML, let's do that here
    analysis_ID = raxml_analysis_ID(alignment_path, model)

    #force raxml to write to the dir with the alignment in it
    aln_dir, fname = os.path.split(alignment_path)
    command = " %s -s '%s' -t '%s' %s -n %s -w '%s' " % (
        bl, alignment_path, tree_path, model_params, analysis_ID, os.path.abspath(aln_dir))
    run_raxml(command)

def raxml_analysis_ID(alignment_path, model):
    dir, file = os.path.split(alignment_path)
    aln_name =  os.path.splitext(file)[0]
    analysis_ID = '%s_%s.txt' %(aln_name, model)
    return analysis_ID

def make_tree_path(alignment_path):
    dir, aln = os.path.split(alignment_path)
    tree_path = os.path.join(dir, "RAxML_parsimonyTree.BLTREE")
    return tree_path

def make_output_path(alignment_path, model):
    analysis_ID = raxml_analysis_ID(alignment_path, model)
    dir, aln_file = os.path.split(alignment_path)
    stats_fname = "RAxML_info.%s" % (analysis_ID)
    stats_path = os.path.join(dir, stats_fname)
    tree_fname = "RAxML_result.%s" % (analysis_ID)
    tree_path = os.path.join(dir, tree_fname)
    return stats_path, tree_path

def remove_files(aln_path, model):
    '''remove all files from the alignment directory that are produced by raxml'''
    dir, file = os.path.split(aln_path)
    analysis_ID = raxml_analysis_ID(aln_path, model)
    dir = os.path.abspath(dir)
    fnames = os.listdir(dir)
    fs = fnmatch.filter(fnames, '*%s*' %analysis_ID) 
    [os.remove(os.path.join(dir,f)) for f in fs]



class raxmlResult(object):
    def __init__(self, lnl, tree_size, seconds):
        self.lnl = lnl
        self.seconds = seconds
        self.tree_size = tree_size

    def __str__(self):
        return "raxmlResult(lnl:%s, tree_size:%s, secs:%s)" % (self.lnl, self.tree_size, self.seconds)

class Parser(object):
    def __init__(self):
        FLOAT = Word(nums + '.-').setParseAction(lambda x: float(x[0]))
        INTEGER = Word(nums + '-').setParseAction(lambda x: int(x[0]))

        OB = Suppress("(")
        CB = Suppress(")")
        LNL_LABEL_1 = Literal("Final GAMMA  likelihood:")
        LNL_LABEL_2 = Literal("Likelihood:")
        TIME_LABEL_1 = Literal("Overall Time for Tree Evaluation")
        TIME_LABEL_2 = Literal("Time for branch length scaler and remaining model parameters optimization:")

        LNL_LABEL = (LNL_LABEL_1|LNL_LABEL_2)
        TIME_LABEL = (TIME_LABEL_1|TIME_LABEL_2)
        TREE_SIZE_LABEL = Literal("Tree-Length:")

        lnl = (LNL_LABEL + FLOAT("lnl"))
        seconds = (TIME_LABEL + FLOAT("seconds"))
        tree_size = (TREE_SIZE_LABEL + FLOAT("tree_size"))

        # Shorthand...
        def nextbit(label, val):
            return Suppress(SkipTo(label)) + val

        # Just look for these things
        self.root_parser = \
                nextbit(TIME_LABEL, seconds) +\
                nextbit(LNL_LABEL, lnl) +\
                nextbit(TREE_SIZE_LABEL, tree_size)

    def parse(self, text):
        log.debug("Parsing raxml output...")
        try:
            tokens = self.root_parser.parseString(text)
        except ParseException, p:
            log.error(str(p))
            raise RaxmlError

        log.debug("Parsed LNL:      %s" %tokens.lnl)
        log.debug("Parsed TREESIZE: %s" %tokens.tree_size)
        log.debug("Parsed TIME:     %s" %tokens.seconds)
            

        return raxmlResult(lnl=tokens.lnl, tree_size=tokens.tree_size, seconds=tokens.seconds)

# Stateless, so safe for use across threads. HMMMM, REALLY?
the_parser = Parser()

def parse(text):
    return the_parser.parse(text)

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    import tempfile, os
    from alignment import TestAlignment
    import raxml_models

    #test with a DNA alignment
    alignment = TestAlignment("""
4 2208
spp1     CTTGAGGTTCAGAATGGTAATGAA------GTGCTGGTGCTGGAAGTTCAGCAGCAGCTCGGCGGCGGTATCGTACGTACCATCGCCATGGGTTCTTCCGACGGTCTGCGTCGCGGTCTGGATGTAAAAGACCTCGAGCACCCGATCGAAGTCCCAGTTGGTAAAGCAACACTGGGTCGTATCATGAACGTACTGGGTCAGCCAGTAGACATGAAGGGCGACATCGGTGAAGAAGAGCGTTGGGCT---------------ATCCACCGTGAAGCACCATCCTATGAAGAGCTGTCAAGCTCTCAGGAACTGCTGGAAACCGGCATCAAAGTTATCGACCTGATGTGTCCGTTTGCGAAGGGCGGTAAAGTTGGTCTGTTCGGTGGTGCGGGTGTAGGTAAAACCGTAAACATGATGGAGCTTATTCGTAACATCGCGATCGAGCACTCCGGTTATTCTGTGTTTGCGGGCGTAGGTGAACGTACTCGTGAGGGTAACGACTTCTACCACGAAATGACCGACTCCAACGTTATCGAT---------------------AAAGTTTCTCTGGTTTATGGCCAGATGAACGAGCCACCAGGTAACCGTCTGCGCGTTGCGCTGACCGGTCTGACCATGGCTGAGAAGTTCCGTGACGAAGGTCGCGACGTACTGCTGTTCGTCGATAACATCTATCGTTACACCCTGGCAGGTACTGAAGTTTCAGCACTGCTGGGTCGTATGCCTTCAGCGGTAGGTTACCAGCCGACTCTGGCGGAAGAAATGGGCGTTCGCATTCCAACGCTGGAAGAGTGTGATATCTGCCACGGCAGCGGCGCTAAAGCCGGTTCGAAGCCGCAGACCTGTCCTACCTGTCACGGTGCAGGCCAGGTACAGATGCGCCAGGGCTTCTTCGCTGTACAGCAGACCTGTCCACACTGCCAGGGCCGCGGTACGCTGATCAAAGATCCGTGCAACAAATGTCACGGTCATGGTCGCGTAGAGAAAACCAAAACCCTGTCCGTAAAAATTCCGGCAGGCGTTGATACCGGCGATCGTATTCGTCTGACTGGCGAAGGTGAAGCTGGTGAGCACGGCGCACCGGCAGGCGATCTGTACGTTCAGGTGCAGGTGAAGCAGCACGCTATTTTCGAGCGTGAAGGCAACAACCTGTACTGTGAAGTGCCGATCAACTTCTCAATGGCGGCTCTTGGCGGCGAGATTGAAGTGCCGACGCTTGATGGTCGCGTGAAGCTGAAAGTTCCGGGCGAAACGCAAACTGGCAAGCTGTTCCGTATGCGTGGCAAGGGCGTGAAGTCCGTGCGCGGCGGTGCACAGGGCGACCTTCTGTGCCGCGTGGTGGTCGAGACACCGGTAGGTCTTAACGAGAAGCAGAAACAGCTGCTCAAAGATCTGCAGGAAAGTTTTGGCGGCCCAACGGGTGAAAACAACGTTGTTAACGCCCTGTCGCAGAAACTGGAATTGCTGATCCGCCGCGAAGGCAAAGTACATCAGCAAACTTATGTCCATGGTGTGCCACAGGCTCCGCTGGCGGTAACCGGTGAAACGGAAGTGACCGGTACACAGGTGCGTTTCTGGCCAAGCCACGAAACCTTCACCAACGTAATCGAATTCGAATATGAGATTCTGGCAAAACGTCTGCGCGAGCTGTCATTCCTGAACTCCGGCGTTTCCATCCGTCTGCGCGATAAGCGTGAC---GGCAAAGAAGACCATTTCCACTATGAAGGTGGTATCAAGGCGTTTATTGAGTATCTCAATAAAAATAAAACGCCTATCCACCCGAATATCTTCTACTTCTCCACCGAA---AAAGACGGTATTGGCGTAGAAGTGGCGTTGCAGTGGAACGATGGTTTCCAGGAAAACATCTACTGCTTCACCAACAACATTCCACAGCGTGATGGCGGTACTCACCTTGCAGGCTTCCGTGCGGCGATGACCCGTACGCTGAACGCTTACATGGACAAAGAAGGCTACAGCAAAAAAGCCAAA------GTCAGCGCCACCGGTGATGATGCCCGTGAAGGCCTGATTGCCGTCGTTTCCGTGAAAGTACCGGATCCGAAATTCTCCTCTCAGACTAAAGACAAACTGGTCTCTTCTGAGGTGAAAACGGCGGTAGAACAGCAGATGAATGAACTGCTGAGCGAATACCTGCTGGAAAACCCGTCTGACGCCAAAATC
spp2     CTTGAGGTACAAAATGGTAATGAG------AGCCTGGTGCTGGAAGTTCAGCAGCAGCTCGGTGGTGGTATCGTACGTGCTATCGCCATGGGTTCTTCCGACGGTCTGCGTCGTGGTCTGGAAGTTAAAGACCTTGAGCACCCGATCGAAGTCCCGGTTGGTAAAGCAACGCTGGGTCGTATCATGAACGTGCTGGGTCAGCCGATCGATATGAAAGGCGACATCGGCGAAGAAGAACGTTGGGCG---------------ATTCACCGTGCAGCACCTTCCTATGAAGAGCTCTCCAGCTCTCAGGAACTGCTGGAAACCGGCATCAAAGTTATCGACCTGATGTGTCCGTTCGCGAAGGGCGGTAAAGTCGGTCTGTTCGGTGGTGCGGGTGTTGGTAAAACCGTAAACATGATGGAGCTGATCCGTAACATCGCGATCGAACACTCCGGTTACTCCGTGTTTGCTGGTGTTGGTGAGCGTACTCGTGAGGGTAACGACTTCTACCACGAAATGACCGACTCCAACGTTCTGGAT---------------------AAAGTATCCCTGGTTTACGGCCAGATGAACGAGCCGCCGGGAAACCGTCTGCGCGTTGCACTGACCGGCCTGACCATGGCTGAGAAATTCCGTGACGAAGGTCGTGACGTTCTGCTGTTCGTCGATAACATCTATCGTTATACCCTGGCCGGTACAGAAGTATCTGCACTGCTGGGTCGTATGCCTTCTGCGGTAGGTTATCAGCCGACGCTGGCGGAAGAGATGGGCGTTCGTATCCCGACGCTGGAAGAGTGCGACGTCTGCCACGGCAGCGGCGCGAAATCTGGCAGCAAACCGCAGACCTGTCCGACCTGTCATGGTCAGGGCCAGGTGCAGATGCGTCAGGGCTTCTTCGCCGTTCAGCAGACCTGTCCGCATTGTCAGGGGCGCGGTACGCTGATTAAAGATCCGTGCAACAAATGTCACGGTCACGGTCGCGTTGAGAAAACCAAAACCCTGTCGGTCAAAATCCCGGCGGGCGTGGATACCGGCGATCGTATTCGTCTGTCAGGAGAAGGCGAAGCGGGCGAACACGGTGCACCAGCAGGCGATCTGTACGTTCAGGTCCAGGTTAAGCAGCACGCCATCTTTGAGCGTGAAGGCAATAACCTGTACTGCGAAGTGCCTATTAACTTCACCATGGCAGCCCTCGGCGGCGAGATTGAAGTCCCGACGCTGGATGGCCGGGTGAATCTCAAAGTGCCTGGCGAAACGCAAACCGGCAAACTGTTCCGCATGCGCGGTAAAGGTGTGAAATCCGTGCGCGGTGGTGCTCAGGGCGACCTGCTGTGCCGCGTGGTGGTTGAAACACCAGTCGGGCTGAACGATAAGCAGAAACAGCTGCTGAAGGACCTGCAGGAAAGTTTTGGCGGACCAACGGGCGAGAAAAACGTGGTTAACGCCCTGTCGCAGAAGCTGGAGCTGGTTATTCAGCGCGACAATAAAGTTCACCGTCAGATCTATGCGCACGGTGTGCCGCAGGCTCCGCTGGCAGTGACCGGTGAGACCGAAAAAACCGGCACCATGGTACGTTTCTGGCCAAGCTATGAAACCTTCACCAACGTTGTCGAGTTCGAATACGAGATCCTGGCAAAACGTCTGCGTGAGCTGTCGTTCCTGAACTCCGGGGTTTCTATCCGTCTGCGTGACAAGCGTGAC---GGTAAAGAAGACCATTTCCACTACGAAGGCGGCATCAAGGCGTTCGTTGAGTATCTCAATAAGAACAAAACGCCGATCCACCCGAATATCTTCTACTTCTCCACCGAA---AAAGACGGTATTGGCGTCGAAGTAGCGCTGCAGTGGAACGACGGCTTCCAGGAAAACATCTACTGCTTCACCAACAACATCCCGCAGCGCGATGGCGGTACTCACCTTGCGGGCTTCCGCGCGGCGATGACCCGTACCCTGAACGCCTATATGGACAAAGAAGGCTACAGCAAAAAAGCCAAA------GTCAGCGCTACCGGCGACGATGCGCGTGAAGGCCTGATTGCCGTTGTCTCCGTGAAGGTTCCGGATCCGAAATTCTCCTCGCAGACCAAAGACAAACTGGTCTCCTCCGAGGTGAAAACCGCGGTTGAACAGCAGATGAATGAACTGCTGAACGAATACCTGCTGGAAAATCCGTCTGACGCGAAAATC
spp3     CTTGAGGTACAGAATAACAGCGAG------AAGCTGGTGCTGGAAGTTCAGCAGCAGCTCGGCGGCGGTATCGTACGTACCATCGCAATGGGTTCTTCCGACGGTCTGCGTCGTGGTCTGGAAGTGAAAGACCTCGAGCACCCGATCGAAGTCCCGGTAGGTAAAGCGACCCTGGGTCGTATCATGAACGTGCTGGGTCAGCCAATCGATATGAAAGGCGACATCGGCGAAGAAGATCGTTGGGCG---------------ATTCACCGCGCAGCACCTTCCTATGAAGAGCTGTCCAGCTCTCAGGAACTGCTGGAAACCGGCATCAAAGTTATCGACCTGATTTGTCCGTTCGCTAAGGGCGGTAAAGTTGGTCTGTTCGGTGGTGCGGGCGTAGGTAAAACCGTAAACATGATGGAGCTGATCCGTAACATCGCGATCGAGCACTCCGGTTACTCCGTGTTTGCAGGCGTGGGTGAGCGTACTCGTGAGGGTAACGACTTCTACCACGAGATGACCGACTCCAACGTTCTGGAC---------------------AAAGTTGCACTGGTTTACGGCCAGATGAACGAGCCGCCAGGTAACCGTCTGCGCGTAGCGCTGACCGGTCTGACCATCGCGGAGAAATTCCGTGACGAAGGCCGTGACGTTCTGCTGTTCGTCGATAACATCTATCGTTATACCCTGGCCGGTACAGAAGTTTCTGCACTGCTGGGTCGTATGCCATCTGCGGTAGGTTATCAGCCTACTCTGGCAGAAGAGATGGGTGTTCGTATCCCGACGCTGGAAGAGTGTGAAGTTTGCCACGGCAGCGGCGCGAAAAAAGGTTCTTCTCCGCAGACCTGTCCAACCTGTCATGGACAGGGCCAGGTGCAGATGCGTCAGGGCTTCTTCACCGTGCAGCAAAGCTGCCCGCACTGCCAGGGCCGCGGTACCATCATTAAAGATCCGTGCACCAACTGTCACGGCCATGGCCGCGTAGAGAAAACCAAAACGCTGTCGGTAAAAATTCCGGCAGGCGTGGATACCGGCGATCGTATCCGCCTTTCTGGTGAAGGCGAAGCGGGCGAGCACGGCGCACCTTCAGGCGATCTGTACGTTCAGGTTCAGGTGAAACAGCACCCAATCTTCGAGCGTGAAGGCAATAACCTGTACTGCGAAGTGCCGATCAACTTTGCGATGGCTGCGCTGGGCGGGGAAATTGAAGTGCCGACCCTTGACGGCCGCGTTAAGCTGAAGGTACCGAGCGAAACGCAAACCGGCAAGCTGTTCCGCATGCGCGGTAAAGGCGTGAAATCCGTACGCGGTGGCGCGCAGGGCGATCTGCTGTGCCGCGTCGTCGTTGAAACTCCGGTTAGCCTGAACGAAAAGCAGAAGAAACTGCTGCGTGATTTGGAAGAGAGCTTTGGCGGCCCAACGGGGGCGAACAATGTTGTGAACGCCCTGTCCCAGAAGCTGGAGCTGCTGATTCGCCGCGAAGGCAAAACCCATCAGCAAACCTACGTGCACGGTGTGCCGCAGGCTCCGCTGGCGGTCACCGGTGAAACCGAACTGACCGGTACCCAGGTGCGTTTCTGGCCGAGCCATGAAACCTTCACCAACGTCACCGAATTCGAATATGACATCCTGGCTAAGCGCCTGCGTGAGCTGTCGTTCCTGAACTCCGGCGTCTCTATTCGCCTGAACGATAAGCGCGAC---GGCAAGCAGGATCACTTCCACTACGAAGGCGGCATCAAGGCGTTTGTTGAGTACCTCAACAAGAACAAAACCCCGATTCACCCGAACGTCTTCTATTTCAGCACTGAA---AAAGACGGCATCGGCGTGGAAGTGGCGCTGCAGTGGAACGACGGCTTCCAGGAAAATATCTACTGCTTTACCAACAACATTCCTCAGCGCGACGGCGGTACTCACCTTGCGGGCTTCCGCGCGGCGATGACCCGTACCCTGAACGCCTATATGGACAAAGAAGGCTACAGCAAAAAAGCCAAA------GTGAGCGCCACCGGTGACGATGCGCGTGAAGGCCTGATTGCCGTAGTGTCCGTGAAGGTGCCGGATCCGAAGTTCTCTTCCCAGACCAAAGACAAACTGGTTTCTTCGGAAGTGAAATCCGCGGTTGAACAGCAGATGAACGAACTGCTGGCTGAATACCTGCTGGAAAATCCGGGCGACGCAAAAATT
spp4     CTCGAGGTGAAAAATGGTGATGCT------CGTCTGGTGCTGGAAGTTCAGCAGCAGCTGGGTGGTGGCGTGGTTCGTACCATCGCCATGGGTACTTCTGACGGCCTGAAGCGCGGTCTGGAAGTTACCGACCTGAAAAAACCTATCCAGGTTCCGGTTGGTAAAGCAACCCTCGGCCGTATCATGAACGTATTGGGTGAGCCAATCGACATGAAAGGCGACCTGCAGAATGACGACGGCACTGTAGTAGAGGTTTCCTCTATTCACCGTGCAGCACCTTCGTATGAAGATCAGTCTAACTCGCAGGAACTGCTGGAAACCGGCATCAAGGTTATCGACCTGATGTGTCCGTTCGCTAAGGGCGGTAAAGTCGGTCTGTTCGGTGGTGCGGGTGTAGGTAAAACCGTAAACATGATGGAGCTGATCCGTAACATCGCGGCTGAGCACTCAGGTTATTCGGTATTTGCTGGTGTGGGTGAGCGTACTCGTGAGGGTAACGACTTCTACCACGAAATGACTGACTCCAACGTTATCGAT---------------------AAAGTAGCGCTGGTGTATGGCCAGATGAACGAGCCGCCGGGTAACCGTCTGCGCGTAGCACTGACCGGTTTGACCATGGCGGAAAAATTCCGTGATGAAGGCCGTGACGTTCTGCTGTTCATCGACAACATCTATCGTTACACCCTGGCCGGTACTGAAGTATCAGCACTGCTGGGTCGTATGCCATCTGCGGTAGGCTATCAGCCAACGCTGGCAGAAGAGATGGGTGTGCGCATTCCAACACTGGAAGAGTGCGATGTCTGCCACGGTAGCGGCGCGAAAGCGGGGACCAAACCGCAGACCTGTCATACCTGTCATGGCGCAGGCCAGGTGCAGATGCGTCAGGGCTTCTTCACTGTGCAGCAGGCGTGTCCGACCTGTCACGGTCGCGGTTCAGTGATCAAAGATCCGTGCAATGCTTGTCATGGTCACGGTCGCGTTGAGCGCAGTAAAACCCTGTCGGTGAAAATTCCAGCAGGCGTGGATACCGGCGATCGCATTCGTCTGACCGGCGAAGGTGAAGCGGGCGAACAGGGCGCACCAGCGGGCGATCTGTACGTTCAGGTTTCGGTGAAAAAGCACCCGATCTTTGAGCGTGAAGATAACAACCTATATTGCGAAGTGCCGATTAACTTTGCGATGGCAGCATTGGGTGGCGAGATTGAAGTGCCGACGCTTGATGGGCGTGTGAACCTGAAAGTGCCTTCTGAAACGCAAACTGGCAAGCTGTTCCGCATGCGCGGTAAAGGCGTGAAATCGGTGCGTGGTGGTGCGGTAGGCGATTTGCTGTGTCGTGTGGTGGTGGAAACGCCAGTTAGCCTCAATGACAAACAGAAAGCGTTACTGCGTGAACTGGAAGAGAGTTTTGGCGGCCCGAGCGGTGAGAAAAACGTCGTAAACGCCCTGTCACAGAAGCTGGAGCTGACCATTCGCCGTGAAGGCAAAGTGCATCAGCAGGTTTATCAGCACGGCGTGCCGCAGGCACCGCTGGCGGTGTCCGGTGATACCGATGCAACCGGTACTCGCGTGCGTTTCTGGCCGAGCTACGAAACCTTCACCAATGTGATTGAGTTTGAGTACGAAATCCTGGCGAAACGCCTGCGTGAACTGTCGTTCCTGAACTCTGGCGTTTCGATTCGTCTGGAAGACAAACGCGAC---GGCAAGAACGATCACTTCCACTACGAAGGCGGCATCAAGGCGTTCGTTGAGTATCTCAACAAGAACAAAACCCCGATTCACCCAACGGTGTTCTACTTCTCGACGGAG---AAAGATGGCATTGGCGTGGAAGTGGCGCTGCAGTGGAACGATGGTTTCCAGGAAAACATCTACTGCTTCACCAACAACATTCCACAGCGCGACGGCGGTACGCACCTGGCGGGCTTCCGTGCGGCAATGACGCGTACGCTGAATGCCTACATGGATAAAGAAGGCTACAGCAAAAAAGCCAAA------GTCAGTGCGACCGGTGACGATGCGCGTGAAGGCCTGATTGCAGTGGTTTCCGTGAAAGTGCCGGATCCGAAATTCTCTTCTCAGACCAAAGATAAGCTGGTCTCTTCTGAAGTGAAATCGGCGGTTGAGCAGCAGATGAACGAACTGCTGGCGGAATACCTGCTGGAAAATCCGTCTGACGCGAAAATC
""")
    tmp = tempfile.mkdtemp()
    pth = os.path.join(tmp, 'test.phy')
    alignment.write(pth)
    tree_path = make_topology(pth, "DNA")
    print "TREE TOPOLOGY: ", tree_path
    tree_path = make_branch_lengths(pth, tree_path, "DNA")
    log.info("Tree is %s:", open(tree_path).read())

    for model in raxml_models.get_all_DNA_models():
        log.info("Analysing using model %s:" % model)
        analyse(model, pth, tree_path, "linked")
        stats_pth, tree_pth = make_output_path(pth, model)
        output = open(stats_pth, 'rb').read()
        res = parse(output)
        log.info("Result is %s", res)

    shutil.rmtree(tmp)

    #test with a Protein alignment
    alignment = TestAlignment("""
4 949
AD00P055  SLMLLISSSIVENGAGTGWTVYPPLSSNIAHSGSSVDLAIFSLHLAGISSILGAINFITTIINMKVNNLFFDQMSLFIWAVGITALLLLLSLPVLAGAITMLLTDRNLNTSFFDPAGGGDPILYQHLFWFFGHPXXXXXXXXXXGIISHIISQESGKKETFGSLGMIYAMLAIGLLGFIVWAHHMFTVGMDIDTRAYFTSATMIIAVPTGIKIFSWLATIYGTQINYSPSMLWSLGFIFLFAVGGLTGVILANSSIDITLHDTYYVVAHFHYVLSMGAIFAIFGGFIHWYPLFTGLMMNSYLLKIQFILMFIGVNXXXXXXXXXXXXXXXXXXXXXPDMXLSWNIISSLGSYMSFISMMMMMMIIWESMIKQRLILFSLNMSSSIEWLQNTPPNEHSYNELPILSNFMATWSNLNFQNSVSPLMEQIIFFHDHSLIILIMITMLLSYMMLSMFWNKFINRFLLEGQMIELIXXXXXXXXXXXXXXXXXRLLYLLDELNNPLITIKSIGHQWYWSYEYSDFKNIEFDSYMINEYNLNNFRLLDVDNRIIIPMNNNIRMLITATDVIHSWTVPSIGVKVDANPGRLNQTSFFINRPGIFFGQCSEICGANHSFMPIVIESISIKNFXDAPGHSDFIKNMITGTSQAXCAVLIVAAGTGEXEAGISKNGQTREHALXAFTLGVKQLIVGVNKMXSTEPPYSESRFEEIKKEVSSYIKKIGYNPAAVAFVPISGWHGDNMLEASTKMPWFKGWQVERKEGKAEGKCLIEALDAILPPARPTDKALRLPLQDVYKIGGIGTVPVGRVETGVLKPGTIVVFAPANITTEVKSVEMHHEXLQEAVPGDNVGFNVKNVSVKELRRGYVAGDTKNNPPKGAADFTAQVIVLNHPGQISNGYTPVLDCHTAHIACKFAEIKEKVDXXSGKSXEVDPKSIKSGDDAXVNMVXSKPLXXES
RV03N585  SLMLLISSSIVENGAGTGWTVYPPLSSNIAHSGSSVDLAIFSLHLAGISSILGAINFITTIINMKVNNLFFDQMSLFIWAVGITALLLLLSLPVLAGAITMLLTDRNLNTSFFDPAGGGDPILYQHLFWFFGHPEVYILILPGFGIISHIISQESGKKETFGSLGMIYAMLAIGLLGFIVWAHHMFTVGMDIDTRAYITSATMIIAVPTGIKIFSWLATIYGTQINYSPSMLWSLGFIFLFAVGGLTGVILANSSIDITLHDTYYVVAHFHYVLSMGAIFAIFGGFIHWYPLFTGLMMNSYLLKIQFILMFIGVNXXXXXXXXXXXXXXXXXXXXXPDMFLSWNIISSLGSYMSFISMMMMMMIIWESMIKQRLILFSLNMSSSIEWLQNTPPNEHSYNELPILSNFMATWSNLNFQNSVSPLMEQIIFFHDHSLIILIMITMLLSYMMLSMFWNKFINRFLLEGQMIEXXXXXXXXIILIFIALPSLRLLYLLDELNNPLITIKSIGHQWYWSYEYSDFKNIEFDSYMINKYNLNNFRLLDVDNRIIIPMNNNIRMLITATDVIHSWTVPSIGVKVDANPGRLNQTSFFINRPGIFFGQCSEICGANHSFMPIVIESISIKNFIDAPGHSDFIKNMITGTSQADCAVLIVAAGTGEFEAGISKNGQTREHALLAFTLGVKQLIVGVNKMDSTEPPYSESRFEEIKKEVSSYIKKIGYNPAAVAFVPISGWHGDNMLEASTKMPWFKGWQVERKEGKAEGKCLIEALDAILPPARPTDKALRLPLQDVYKIGGIGTVPVGRVETGVLKPGTIVVFAPANITTEVKSVEMHHEALQEAVPGDNVGFNVKNVSVKELRRGYVAGDTKNNPPKGAADFTAQVIVLNHPGQISNGYTPVLDCHTAHIACKFAEIKEKVDRRSGKSTEVDPKSIKSGDAAIVNLVPSKPLCVES
TDA99Q996 SLMLLISSSIVENGAGTGWTVYPPLSSNIAHSGSSVDLAIFSLHLAGISSILGAINFITTIINMKVNNMSFDQMSLFIWAVGITALLLLLSLPVLAGAITMLLTDRNLNTSFFDPAGGGDPILYQXXXXXXXXXXXXXXXXXXXXIISXIISQESXKKETFGSLGMIYAMLAIGLLGFIVWAHHMFTVGMDIDTRAYFTSATMIIAVPTGIKIFSWLATIYGSQINYSPSMLWSLGFIFLFAVGGLTGVILANSSIDITLHDTYYVVAHFHYVLSMGAIFAIFGGFIHWYPLFTGLMMNSYLLXIXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXLSWNIVSSLGSYMSFISMLLMMMIIWESMIKKRLILFSLNMSSSIEWLQNTPPNEHSYNELPILNNFMATWSNLNFQNSVSPLMEQIIFFNDHSLIILIMITMLLSYMMLSMFWNKFINRFLLEGQMXXLIXXXXXXXXXXXXXXXSLRLLYLLDELNNPLITIKSIGHQWYWSYEYSDFKNIEFDSYMINEYNLNNFRLLDVDNRIIIPMNNNIRMLITATDVIHSWTIPAIGVKVDANPGRLNQSSFFINRPGIFFGQCSEICGANHSFMPIVIESISIKNFIDAPGHSDFIKNMITGTSQADCAVLIVAAGTGEFEAGISKNGQTREHALLAFTLGVKQLIVGVNKMDSTEPPYSESRFEEIKKEVSSYIKKIGYNPAAVAFVPISGWHGDNMLEASTKMPWFKGWQVERKEGKAEGKCLIEALDAILPPARPTDKALRLPLQDVYKIGGIGTVPVGRVETGVLKPGTIVVFAPANITTEVKSVEMHHEALQEAVPGDNVGFNVKNVSVKELRRGYVAGDTKNNPPKGAADFTAQVIVLNHPGQISNGYTPVLDCHTAHIACKFAEIKEKVDRRSGKSTEVDPKSIKSGDAAIVNLVPSKPLCVES
ZD99S305  SLMLLISSSIVENGAGTGWTVYPPLSSNIAHSGSSVDLAIFSLHLAGISSILGAINFITTIINMKVNNLFFDQMSLFIWAVGITALLLLLSLPVLAGAITMLLTDRNLNTSFFDPAGGGDPILYQHLFWFFGHPXXXXXXXXXXXXXXXXXXXESGKKETFGSLGMIYAMLAIGLLGFIVWAHHMFTVGMDIDTRAYFTSATMIIAVPTGIKIFSWLATIYGTQINYSPSMLWSLGFIFLFAVGGLTGVILANSSIDITLHDTYYVVAHFHYVLSMGAIFAIFGGFIHWYPLFTGLMMNSYLLKIQFILMXXXXXXXXXXXXXXXXXXXXXXXXXXPDMXLSWNIISSLGSYMSFISMMMMMMIIWESMIKQRLILFSLNMSSSIEWLQNTPPNEHSYNELPILSNFMATWSNLNFQNSVSPLMEQIIFFHDHSLIILIMITMLLSYMMLSMFWNKFINRFLLEGQMIELIXXXXXXIILIFIALPSLRLLYLLDELNNPLITIKSIGHQWYWSYEYSDFKNIEFDSYMINEYNLNNFRLLDVDNRIIIPMNNNIRMLITATDVIHSWTVPSIGVKVDANPGRLNQTSFFINRPGIFFGQCSEICGANHSFMPIVIESISIKNFIDAPGHSDFIKNMITGTSQADCAVLIVAAGTGEFEAGISKNGQTREHALLAFTLGVKQLIVGVNKMDSTEPPYSESRFEEIKKEVSSYIKKIGYNPAAVAFVPISGWHGDNMLEASTKMPWFKGWQVERKEGKAEGKCLIEALDAILPPARPTDKALRLPLQDVYKIGGIGTVPVGRVETGVLKPGTIVVFAPANITTEVKSVEMHHEALQEAVPGDNVGFNVKNVSVKELRRGYVAGDTKNNPPKGAADFTAQVIVLNHPGQISNGYTPVLDCHTAHIACKFAEIKEKVDRRSGKSTEVDPKSIKSGDAAIVNLVPSKPLCVES
""")

    tmp = tempfile.mkdtemp()
    pth = os.path.join(tmp, 'test.phy')
    alignment.write(pth)
    tree_path = make_topology(pth, "protein")
    print "TREE TOPOLOGY: ", tree_path
    tree_path = make_branch_lengths(pth, tree_path, "protein")
    log.info("Tree is %s:", open(tree_path).read())

    for model in raxml_models.get_all_protein_models():
        log.info("Analysing using model %s:" % model)
        analyse(model, pth, tree_path, "linked")
        stats_pth, tree_pth = make_output_path(pth, model)
        output = open(stats_pth, 'rb').read()
        res = parse(output)
        log.info("Result is %s", res)

    shutil.rmtree(tmp)
