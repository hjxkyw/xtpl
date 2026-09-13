# xtpl_grammar.raku -- the parts of xtpl parsed by a real grammar.
#
# Driven from Python through rakulang, which embeds Raku++ as a shared
# library. The transpiler falls back to its regex scanner when rakulang is
# not installed; both must produce identical output, and the golden tests
# are what hold them to it.
#
# So far: the declarator list, and the postfix if/while modifiers. Everything
# else in xtpl is still scanned line by line.
#
# --------------------------------------------------------------------------------
# The Raku notation used below, since it is dense and easy to misread:
#
#   token / rule    Both are productions. 'rule' is 'token' with :sigspace --
#                   it inserts whitespace matching between atoms. That breaks
#                   a non-greedy body match, so anything using [.+?] must be
#                   a 'token' with explicit \s+.
#
#   $<name> = X     A named capture: match X, and file it under 'name'. Not an
#                   assignment, and not a production -- you cannot reference
#                   <name> elsewhere. To get a real production, give the piece
#                   its own token, as 'assign' below does.
#
#   .+?             Non-greedy: take as few characters as possible, then extend
#                   until the rest of the pattern matches. '.' includes spaces.
#                   Greedy '.+' would run to the LAST match of what follows,
#                   or fail outright.
#
#   'a' ~ 'b' BODY  The goal operator. Opener, closer, then the body -- the
#                   closer is declared up front so the parser can report which
#                   construct was left open. It reads backwards; it is not
#                   string concatenation, which is what '~' means outside a
#                   regex.
#
#   « ... »         Word boundaries. '« "if" »' matches a standalone 'if' and
#                   not the 'if' inside 'iif(', which is the whole reason the
#                   postfix rule needs no blacklist of line prefixes.
#
#   <!name>         Negative lookahead: fail here if 'name' would match, and
#                   consume nothing.
#
#   X+ % ','        One or more X, separated by commas. '%' here is a
#                   separator, not modulo.
#
#   make / .made    An actions class attaches a value to the current match with
#                   'make', and reads what a sub-match attached with '.made'.
#                   Actions fire bottom-up, so a production's children have
#                   already made their values by the time it runs. '.made' is
#                   Nil where no action ran, which is why every production that
#                   yields a value has a method here.
# --------------------------------------------------------------------------------

grammar XtplDecl {
    # '%' and not '%%': the two differ only in whether a trailing separator is
    # allowed, and 'local a := 1,' is a typo rather than a declaration list of
    # one. '%%' accepted it silently and dropped the empty tail.
    #
    # The '$' is belt and braces. Trailing garbage was already refused --
    # 'a := 1)' does not parse, because ')' is neither a value character nor
    # the start of a group -- but the anchor says so rather than leaving it to
    # be inferred from the value token's character class.
    rule TOP { <declarator>+ % ',' $ }

    rule declarator {
        <name> <attributes>? <typing>? [ <init> | <rejected-init> ]?
    }

    # TLPP's own type annotation: 'local oTool as object'. Kept and emitted
    # back out -- xtpl has no business making anyone drop it.
    rule typing { :i 'as' <name> }

    # The operator is its own production in each form. Which of the two
    # matched is sorted out in the actions, not hidden behind an alias here.
    rule init { <assign> <value> }

    # '?=' assigns only when the target is Nil, so it is an operator on a
    # variable that already exists, never a declaration form. It is matched
    # here purely so the transpiler can say that; a grammar that refused it
    # would report 'cannot read declaration' and leave the writer guessing.
    rule rejected-init { <rejected-assign> <value> }

    token assign          { ':=' }
    token rejected-assign { '?=' }

    # local aWork <contained, const> := {}
    #
    # A 'token' with the spacing written out, not a 'rule'. As a rule this
    # accepted '< contained>' but rejected '<contained >': :sigspace inserts
    # whitespace between atoms, and the closer supplied by the goal operator
    # is not a position it inserts at. Spelling both sides out makes the two
    # symmetrical, which is what anyone writing the attribute would expect.
    token attributes { '<' \s* <name>+ % [ \s* ',' \s* ] \s* '>' }

    token name { <[ a..z A..Z _ ]> <[ a..z A..Z 0..9 _ ]>* }

    # An initialiser runs to the next comma that is not inside brackets. The
    # nested rules are what let '{1, 2}' stay with its own declarator.
    #
    # There is no string literal here on purpose: the transpiler masks every
    # literal and comment before any pass sees a line, so by the time this
    # grammar runs, 'local x := "a, b", y := "c"' has become
    # 'local x := <token>, y := <token>' and the comma inside the string does
    # not exist. Teaching the grammar about quotes would duplicate the masking
    # and could disagree with it. Parsed on its own, unmasked, this grammar
    # would get that line wrong -- which is worth knowing before reusing it
    # anywhere else.
    # A run of ordinary characters, or a bracketed group. Quantifying the
    # character class rather than matching one at a time is about twice as
    # fast, and says what it means.
    token value  { [ <group> | <-[ , ( ) \{ \} \[ \] ]>+ ]+ }
    token group  { <paren> | <brace> | <brack> }
    token paren  { '(' ~ ')' <inner>* }
    token brace  { '{' ~ '}' <inner>* }
    token brack  { '[' ~ ']' <inner>* }
    token inner  { <group> | <-[ ( ) \{ \} \[ \] ]>+ }
}

class XtplDeclActions {
    method TOP($/) { make $<declarator>.map(*.made) }

    # Each production that yields a value has its own method, so every read
    # below is '.made' rather than a reach into the raw match tree.
    method init($/)          { make %( assign => ~$<assign>,
                                       value  => ~$<value>.trim ) }
    method rejected-init($/) { make %( assign => ~$<rejected-assign>,
                                       value  => ~$<value>.trim ) }

    method declarator($/) {
        # whichever initialiser matched, if the declarator had one at all
        my $initialiser = ($<init> // $<rejected-init>).?made;
        make %(
            name   => ~$<name>,
            attrs  => $<attributes> ?? $<attributes>.made !! [],
            typing => $<typing> ?? ~$<typing><name> !! '',
            assign => $initialiser ?? $initialiser<assign> !! '',
            value  => $initialiser ?? $initialiser<value>  !! '',
        )
    }

    # '.Array' reifies the Seq that .map returns. Dropping it produces the
    # same list here, since rakulang reifies whatever it is handed on the way
    # to Python -- so this is defensive, not required. It is kept because a
    # Seq can only be consumed once, and 'made' values are read more than once
    # by the caller in XtplDecl::declarator below.
    method attributes($/) { make $<name>.map(~*).Array }
}


# --------------------------------------------------------------------------------
# Postfix modifiers: 'return x if c', 'exec f() if c', 'x := 1 if c',
# 'f() while c'.
#
# The regex this replaces had to be guarded by a blacklist of line prefixes,
# because it could not tell a real 'if' statement from a postfix one, nor an
# 'if' inside a word. A grammar tells them apart by structure: the body is a
# sequence of tokens, so the 'if' inside 'iif(' is part of an identifier and
# never a keyword.
# --------------------------------------------------------------------------------

grammar XtplPostfix {
    # 'token', not 'rule': the implicit whitespace a rule inserts between
    # atoms defeats the non-greedy body match.
    #
    # '\h*' leads because the alternatives below anchor at the start. The
    # transpiler hands this a stripped line, so nothing depended on it, but
    # without it an indented 'return x if c' fell through to <plain> and came
    # back as a plain statement -- silently losing the pending defers. A
    # grammar that only works on pre-stripped input is a trap for the next
    # caller.
    #
    # '||' and not '|': ordered alternation, so the specific forms are tried
    # before the general one. Longest-token matching happens to give the same
    # answer today, because all three alternatives end at the same place and
    # ties fall to the first -- but that is a coincidence of these three
    # patterns, not a property being relied on. XtplExpr states its ordering
    # the same way.
    token TOP { \h* <!control> [ <ret> || <exec> || <plain> ] $ }

    # the bare form first, so 'return if c' is a return and not a body
    # that happens to be the word 'return'
    #
    # '»' rather than '\s+': a word boundary, so 'return(x) if c' is a return
    # too. Requiring whitespace sent it to <plain>, and the transpiler then
    # matched it against its own 'return' prefix test, emitted the pending
    # defers, and passed the line through untouched -- 'return(x) if c'
    # reached the .tlpp verbatim. The regex path had always accepted it, so
    # the two paths disagreed, which is the thing the golden tests exist to
    # stop. '\h*' after the boundary, not '\s+', because there is no space
    # between 'return' and '('.
    token ret   { 'return' » \h* <modifier>
               || 'return' » \h* $<value> = [.+?] \s+ <modifier> }
    token exec  { 'exec' » \h+ $<value> = [.+?] \s+ <modifier> }

    # Deliberately broad: anything with a trailing modifier. It reads the last
    # standalone 'if' or 'while' on the line, which is safe only because the
    # transpiler masks comments and strings first -- unmasked,
    # 'x := 1 // initialize if needed if y' splits inside the comment. Another
    # pass that wanted to reuse this grammar would have to mask first too.
    token plain { $<value> = [.+?] \s+ <modifier> }

    # '«' before the keyword is what stops 'iif(' from reading as 'if':
    # inside a word there is no boundary, so only a standalone one matches.
    token modifier { « $<kw> = [ 'if' | 'while' ] » \s+ $<cond> = [.+] }

    # A line that opens or closes a block is never a postfix modifier:
    # wrapping one in a generated If would break the structure it belongs to.
    # The test for membership here is exactly that -- does the word open or
    # close a block -- which is why 'exit' and 'loop' are absent. They are
    # ordinary statements, and 'exit if nX > 5' is a useful thing to write.
    #
    # 'return' is absent for a different reason: <ret> handles it, and listing
    # it here would refuse every postfix return.
    #
    # The structured-exception and declaration words were added after review.
    # None of them could reach here carrying a standalone 'if' today, so this
    # is insurance rather than a fix -- but the cost is a word in a list and
    # the failure it prevents is silent.
    token control {
        \s* « [ 'if' | 'elseif' | 'endif' | 'else' | 'while' | 'enddo' | 'for'
              | 'next' | 'end' | 'do' | 'case' | 'otherwise' | 'endcase'
              | 'begin' | 'sequence' | 'recover' | 'always' | 'endsequence'
              | 'try' | 'catch' | 'endtry' | 'class' | 'endclass' | 'method'
              | 'function' | 'static' | 'user' | 'local' | 'private'
              | 'public' ] »
    }
}

class XtplPostfixActions {
    method TOP($/) { make ($<ret> // $<exec> // $<plain>).made }
    method ret($/)   { make %( kind => 'return', :body($<value> ?? ~$<value>.trim !! ''),
                               :op(~$<modifier><kw>), :cond(~$<modifier><cond>.trim) ) }
    method exec($/)  { make %( kind => 'exec',   :body(~$<value>.trim),
                               :op(~$<modifier><kw>), :cond(~$<modifier><cond>.trim) ) }
    method plain($/) { make %( kind => 'plain',  :body(~$<value>.trim),
                               :op(~$<modifier><kw>), :cond(~$<modifier><cond>.trim) ) }
}


# --------------------------------------------------------------------------------
# Feed chains: 'aOrders |> filter(...) |> map(...)'.
#
# This is a tokenizer rather than a chain parser. It reports where the
# structure is -- brackets, commas, code blocks, feeds -- and the transpiler
# walks the result. Splitting the work that way keeps the pipeline error
# messages in Python, where the line number lives.
#
# It replaces three hand-rolled delimiter counters and a guard on the previous
# character, which existed so that the '||' opening a zero-argument code block
# could not be read as a feed. Here the block's parameter list is consumed by
# the brace that opens it, so the question never arises -- and the same capture
# is what tells '{|o| o:nValue}' from the array literal '{1, 2}', which the
# line scanner could not do at all.
# --------------------------------------------------------------------------------

grammar XtplExpr {
    token TOP { <node>* $ }

    # '||' is ordered alternation, not longest-token: <feed> must get first
    # refusal on a '|', and <group> must be tried before the text run that
    # would otherwise swallow the bracket opening it.
    token node { <group> || <feed> || <comma> || <text> || <pipe> }

    token feed  { '|>' }
    token comma { ',' }

    # Everything that is not structure. The class excludes '|' so that <feed>
    # sees it first; a '|' that turns out not to begin a feed comes back
    # through <pipe> as ordinary text.
    token text { <-[ ( ) \[ \] \{ \} , | ]>+ }
    token pipe { '|' }

    token group { <paren> || <brack> || <brace> }

    # The closer is a capture rather than part of the pattern. An unclosed
    # group still parses, and 'close' comes back empty, so rendering a node
    # list always reproduces the text it was built from -- no fabricated
    # bracket appears in a line that never had one.
    token paren { '(' <node>* $<close> = [ ')' ]? }
    token brack { '[' <node>* $<close> = [ ']' ]? }

    # A brace opens a code block when a parameter list follows it immediately,
    # and an array or hash literal when it does not.
    token brace { '{' $<head> = [ '|' <-[ | ]>* '|' ]? <node>* $<close> = [ '}' ]? }
}

class XtplExprActions {
    method TOP($/)   { make $<node>.map(*.made).Array }
    method node($/)  { make ($<group> // $<feed> // $<comma> // $<text> // $<pipe>).made }

    method feed($/)  { make %( k => 'feed' ) }
    method comma($/) { make %( k => 'comma' ) }
    method text($/)  { make %( k => 'text', t => ~$/ ) }
    method pipe($/)  { make %( k => 'text', t => '|' ) }

    method group($/) { make ($<paren> // $<brack> // $<brace>).made }

    method paren($/) { make %( k => 'group', open => '(', head => '',
                               items => $<node>.map(*.made).Array,
                               close => ($<close> ?? ~$<close> !! '') ) }
    method brack($/) { make %( k => 'group', open => '[', head => '',
                               items => $<node>.map(*.made).Array,
                               close => ($<close> ?? ~$<close> !! '') ) }
    method brace($/) { make %( k => 'group', open => '{',
                               head  => ($<head>  ?? ~$<head>  !! ''),
                               items => $<node>.map(*.made).Array,
                               close => ($<close> ?? ~$<close> !! '') ) }
}


# --------------------------------------------------------------------------------
# Loop headers: 'for x[, i] in <source>' and 'for <count> times'.
#
# No 'each'. The three for-forms are told apart by structure -- ':=' for the
# counted form, a trailing 'times', a standalone 'in' -- so the word carried
# no information. It also borrowed Harbour's spelling for something narrower
# than Harbour's: that FOR EACH walks hashes, strings and objects too, and
# this one walks arrays and the two sources.
#
# Three regexes used to be tried in a fixed order, each anchored to the end of
# the line. Ordered alternation states that precedence instead of leaving it
# implicit in the sequence of Python 'if's, and puts the more specific form
# first: 'for oItem in aTimes' walks a list, not a count that happens to
# end in the word.
#
# Plain 'for x := ...' is deliberately absent. It is handled after these two
# and is a different shape -- it declares or reuses a counter -- so folding it
# in would buy ordering it already has.
#
# A trailing comment is peeled off in Python before this runs, by both the
# grammar path and the fallback, because only the transpiler knows whether a
# masked token is a comment or a string literal.
# --------------------------------------------------------------------------------

grammar XtplFor {
    token TOP { $<indent> = [ \h* ] [ <foreach> || <fortimes> ] \h* $ }

    token foreach {
        :i 'for' \h+ $<elem> = [ <.name> ]
        [ \h* ',' \h* $<index> = [ <.name> ] ]?
        \h+ 'in' \h+ $<source> = [ \N+ ]
    }

    # The count runs up to the closing keyword. 'times' terminates it inside
    # this token, so the non-greedy run never has to extend past the token
    # boundary -- which 'token' forbids, being :ratchet.
    token fortimes { :i 'for' \h+ $<count> = [ .+? ] \h+ 'times' }

    token name { <[ a..z A..Z _ ]> <[ a..z A..Z 0..9 _ ]>* }
}

class XtplForActions {
    method TOP($/) {
        my %r = ($<foreach> // $<fortimes>).made;
        %r<indent> = ~$<indent>;
        make %r
    }
    method foreach($/)  { make %( kind => 'foreach', elem => ~$<elem>,
                                  index  => ($<index> ?? ~$<index> !! ''),
                                  source => ~$<source>.trim ) }
    method fortimes($/) { make %( kind => 'fortimes', count => ~$<count>.trim ) }
}
