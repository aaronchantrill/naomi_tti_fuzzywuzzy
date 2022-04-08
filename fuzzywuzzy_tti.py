# -*- coding: utf-8 -*-
import logging
import os
import re
from fuzzywuzzy import process
from jiwer import wer
from naomi import paths
from naomi import plugin
from naomi import profile
from pprint import pprint

# Convert a word ("word") to a keyword ("{word}")
def to_keyword(word):
    return "{}{}{}".format("{", word, "}")


class FuzzyWuzzyTTIPlugin(plugin.TTIPlugin):
    def __init__(self, *args, **kwargs):
        self._logger = logging.getLogger(__name__)

    def add_intents(self, intents):
        for intent in intents:
            # this prevents collisions between intents by different authors
            intent_base = intent
            intent_inc = 0
            locale = profile.get("language")
            while intent in self.intent_map['intents']:
                intent_inc += 1
                intent = "{}{}".format(intent_base, intent_inc)
            if('locale' in intents[intent_base]):
                # If the selected locale is not available, try matching just
                # the language ("en-US" -> "en")
                if(locale not in intents[intent_base]['locale']):
                    for language in intents[intent_base]['locale']:
                        if(language[:2] == locale[:2]):
                            locale = language
                            break
            if(locale not in intents[intent_base]['locale']):
                raise KeyError("Language not supported")
            if('keywords' in intents[intent_base]['locale'][locale]):
                if intent not in self.keywords:
                    self.keywords[intent] = {}
                for keyword in intents[intent_base]['locale'][locale]['keywords']:
                    if keyword not in self.keywords[intent]:
                        self.keywords[intent][keyword] = []
                    self.keywords[intent][keyword].extend([word.upper() for word in intents[intent_base]['locale'][locale]['keywords'][keyword]])
            self.intent_map['intents'][intent] = {
                'action': intents[intent_base]['action'],
                'name': intent_base,
                'templates': [],
                'words': {}
            }
            for phrase in intents[intent_base]['locale'][locale]['templates']:
                # Save the phrase so we can search for undefined keywords
                # Convert the template to upper case
                phrase = self.cleantext(phrase)
                self.intent_map['intents'][intent]['templates'].append(phrase)

    def train(self):
        self.trained = True

    def get_plugin_phrases(self, passive_listen=False):
        phrases = []
        # include the keyword, otherwise
        if(passive_listen):
            keywords = profile.get(["keyword"])
            if not (isinstance(keywords, list)):
                keywords = [keywords]
            phrases.extend([word.upper() for word in keywords])
        # Include any custom phrases (things you say to Naomi
        # that don't match plugin phrases). Otherwise, there is
        # a high probability that something you say will be
        # interpreted as a command. For instance, the
        # "check_email" plugin has only "EMAIL" and "INBOX" as
        # standard phrases, so every time I would say
        # "Naomi, check email" Naomi would hear "NAOMI SHUT EMAIL"
        # and shut down.
        custom_standard_phrases_file = paths.data(
            "standard_phrases",
            "{}.txt".format(profile.get(['language'], 'en-US'))
        )
        if(os.path.isfile(custom_standard_phrases_file)):
            with open(custom_standard_phrases_file, mode='r') as f:
                for line in f:
                    phrase = line.strip()
                    if phrase:
                        phrases.append(phrase.upper())

        for intent in self.intent_map['intents']:
            if('templates' in self.intent_map['intents'][intent]):
                templates = self.intent_map['intents'][intent]['templates']
                if(intent in self.keywords):
                    keywords = self.keywords[intent]
                    for keyword in keywords:
                        # This will not replace keywords that do not have a list associated with them, like regex and open keywords
                        # print("Replacing {} with words from {} in templates".format(keyword,keywords[keyword]))
                        for template in templates:
                            if(to_keyword(keyword) in template):
                                templates.extend([template.replace(to_keyword(keyword), word.upper()) for word in keywords[keyword]])
                            # Now that we have expanded every instance of keyword in templates, delete any template that still contains keyword
                            templates = [template for template in templates if not to_keyword(keyword) in template]
                phrases.extend(templates)
        return sorted(phrases)

    def determine_intent(self, phrase):
        phrase = self.cleantext(phrase)
        score = {}
        allvariants = {phrase: {}}
        for intent in self.keywords:
            variants = {phrase: {}}
            for keyword in self.keywords[intent]:
                for word in self.keywords[intent][keyword]:
                    count = 0  # count is the index of the match we are looking for
                    countadded = 0  # keep track of variants added for this count
                    while True:
                        added = 0  # if we get through all the variants without
                        # adding any new variants, then increase the count.
                        for variant in variants:
                            # print("Count: {} Added: {} CountAdded: {}".format(count, added, countadded))
                            # print()
                            # print("word: '{}' variant: '{}'".format(word,variant))
                            # subs is a list of substitutions
                            subs = dict(variants[variant])
                            # check and see if we can make a substitution and
                            # generate a new variant.
                            # print("replacenth('{}', '{}', '{}', {})".format(word, '{'+keyword+'}', variant, count))
                            new = self.replacenth(word, "{}{}{}".format('{', keyword, '}'), variant, count)
                            # print(new)
                            # print()
                            # print(new)
                            if new not in variants:
                                # print(new)
                                try:
                                    subs[keyword].append(word)
                                except KeyError:
                                    subs[keyword] = [word]
                                # print(subs[keyword])
                                # print()
                                variants[new] = subs
                                # pprint(variants)
                                added += 1
                                countadded += 1
                                # start looping over variants again
                                break
                        # check if we were able to loop over all the variants
                        # without creating any new ones
                        if added == 0:
                            if countadded == 0:
                                break
                            else:
                                count += 1
                                countadded = 0
            allvariants.update(variants)
        # Now calculate a total score for each variant
        variantscores = {}
        for variant in allvariants:
            self._logger.info(f"Variant: {variant}")
            # print(f"Variant: {variant}")
            variantscores[variant] = {}
            intentscores = {}
            totalscore = 0
            for intent in self.intent_map['intents']:
                print(f"Intent: {intent}")
                pprint(self.intent_map['intents'][intent]['templates'])
                # use fuzzywuzzy to get the best intent for this variant
                besttemplate, bestscore = process.extractOne(variant, self.intent_map['intents'][intent]['templates'])
                intentscores[intent] = {}
                intentscores[intent]['score'] = bestscore
                intentscores[intent]['template'] = besttemplate
                totalscore += bestscore
                print(f"Intent '{intent}' best template: '{besttemplate}': {bestscore}")
            # list intents and scores
            for intent in intentscores.keys():
                self._logger.info("\t{}: {}".format(intent, intentscores[intent]['score']))
            # Take the intent with the highest score
            bestintent = max(intentscores, key=lambda key: intentscores[key]['score'])
            bestscore = intentscores[bestintent]['score']
            self._logger.info(f"Best intent: {bestintent} template: {intentscores[bestintent]['template']} score: {bestscore}")
            # Change the intent scores into probabilities
            #if(totalscore > 0):
            #    bestscore = intentscores[bestintent]['score'] / totalscore
            #else:
            #    bestscore = 0
            variantscores[variant] = {
                'intent': bestintent,
                'input': phrase,
                'score': bestscore,
                'template': intentscores[bestintent]['template'],
                'matches': allvariants[variant],
                'action': self.intent_map['intents'][bestintent]['action']
            }
        pprint(variantscores)
        bestvariant = max(variantscores, key=lambda key: variantscores[key]['score'])
        self._logger.info(f"Best Variant: {bestvariant}")
        # print(f"Best Variant: {bestvariant}")
        # pprint(variantscores[bestvariant])
        # find the template with the smallest levenshtein distance
        besttemplate = variantscores[bestvariant]['template']
        self._logger.info(f"Best Template: {besttemplate}")
        # print(f"Best Template: {besttemplate}: {variantscores[bestvariant]['score']}")
        # The next thing we have to do is match up all the substitutions
        # that have been made between the template and the current variant
        # This is so that if there are multiple match indicators we can eliminate
        # the ones that have matched.
        # Consider the following:
        #   Team: ['bengals','patriots']
        #   Template: will the {Team} play the {Team} {Day}
        #   Input: will done browns play the bengals today
        #   Input with matches: will done browns play the {Team} {Day}
        #   Matches: {Team: bengals, Day: today}
        # Obviously there is a very low Levenshtein distance between the template
        # and the input with matches, but it's not that easy to figure out which
        # Team in the template has been matched. So loop through the matches and
        # words and match the word with each possible location in the template
        # and take the best as the new template.
        #   Template1: will the bengals play the {Team} {Day}
        #   input: will done browns play the bengals {Day}
        #   distance: .42
        #
        #   Template2: will the {Team} play the bengals {Day}
        #   input: will done browns play the bengals {Day}
        #   distance: .28
        #
        # since we are looking for the smallest distance, Template2 is obviously
        # a better choice.
        # print("Best variant: {}".format(bestvariant))
        # print("Best template: {}".format(besttemplate))
        currentvariant = bestvariant
        currenttemplate = besttemplate
        for matchlist in variantscores[bestvariant]['matches']:
            for word in variantscores[bestvariant]['matches'][matchlist]:
                # Substitute word into the variant (we know this matches the
                # first occurrance of {matchlist})
                currentvariant = bestvariant.replace(
                    "{}{}{}".format('{', matchlist, '}'),
                    word,
                    1
                )
                self._logger.info("Bestvariant with substitutions: {}".format(currentvariant))
                templates = {}
                # Get a count of the number of matches for the
                # current matchlist in template
                possiblesubstitutions = currenttemplate.count(
                    '{}{}{}'.format('{', matchlist, '}')
                )
                # print("Matchlist: {} Word: {} Subs: {}".format(matchlist, word, possiblesubstitutions))
                # We don't actually know if there are actually any
                # substitutions in the template
                if(possiblesubstitutions > 0):
                    for i in range(possiblesubstitutions):
                        # print("replacenth('{}','{}','{}',{})".format(
                        #     '{}{}{}'.format('{', matchlist, '}'),
                        #     word,
                        #     currenttemplate,
                        #     i + 1
                        # ))
                        currenttemplate = self.replacenth(
                            '{}{}{}'.format('{', matchlist, '}'),
                            word,
                            currenttemplate,
                            i + 1
                        )
                        # print("CurrentTemplate = {}".format(currenttemplate))
                        templates[currenttemplate] = wer(
                            currentvariant,
                            currenttemplate
                        )
                    currenttemplate = min(
                        templates,
                        key=lambda key: templates[key]
                    )
                    # print(currenttemplate)
                # print("{}: {}".format(word,currenttemplate))
            # print("{}: {}".format(matchlist,currenttemplate))
        # Now that we have a matching template, run through a list of all
        # substitutions in the template and see if there are any we have not
        # identified yet.
        substitutions = re.findall(r'{(.*?)}', currenttemplate)
        # print("Substitutions: {}".format(substitutions))
        if(substitutions):
            for substitution in substitutions:
                subvar = "{}{}{}".format('{', substitution, '}')
                # print("Searching for {}".format(subvar))
                # So now we know that we are missing the variable contained
                # in substitution.
                # What we have to do now is figure out where in the string
                # to insert that variable in order to minimize the levenshtein
                # distance between bestvariant and besttemplate
                # print("Minimizing distance from '{}' to '{}' by substituting in '{}'".format(currentvariant,currenttemplate,subvar))
                # print("Variant: {}".format(currentvariant))
                variant = currentvariant.split()
                variant.append("<END>")
                # print("Template: {}".format(currenttemplate))
                template = currenttemplate.split()
                template.append("<END>")
                n = len(variant) + 1
                m = len(template) + 1
                # print("Variant: '{}' length: {}".format(variant,n))
                # print("Template: '{}' length: {}".format(template,m))
                # Find out which column contains the first instance of substitution
                s = template.index(subvar) + 1
                # print("subvar={} s={}".format(subvar,s))
                match = []
                a = []
                for i in range(n + 1):
                    a.append([1] * (m + 1))
                    a[i][0] = i
                for j in range(m + 1):
                    a[0][j] = j
                for i in range(1, n):
                    for j in range(1, m):
                        # print("{},{} V: {} T: {}".format(i,j,variant[i-1],template[j-1]))
                        if(variant[i - 1] == template[j - 1]):
                            c = 0
                        else:
                            c = 1
                        a[i][j] = c
                # pprint(a)
                # examine the resulting list of matched words
                # to locate the position of the unmatched keyword
                matched = ""
                for i in range(1, n - 1):
                    # print("i: {} s: {}".format(i,s))
                    if(a[i - 1][s - 1] == 0):
                        # the previous item was a match
                        # so start here and work to the right until there is another match
                        k = i
                        start = k
                        end = n - 1
                        compare = [k]
                        compare.extend([1] * (m))
                        # print(variant[k])
                        # print("Comparing {} to {}".format(a[k],compare))
                        while((a[k] == compare) and (k < (n))):
                            # print("k = {}".format(k))
                            match.append(variant[k - 1])
                            # print(match)
                            k += 1
                            compare = [k]
                            compare.extend([1] * (m))
                            # print("Comparing {} to {}".format(a[k],compare))
                            end = k
                        matched = " ".join(match)
                        # print("Variant:")
                        # pprint(variant)
                        # print("Start: {} End: {}".format(start,end))
                        substitutedvariant = variant[:start]
                        substitutedvariant.append(subvar)
                        substitutedvariant.extend(variant[end:])
                        # print("SubstitutedVariant: {}".format(substitutedvariant))
                        break
                    elif(a[i + 1][s + 1] == 0):
                        # the next item is a match, so start working backward
                        k = i
                        end = k
                        start = 0
                        compare = [k]
                        compare.extend([1] * (m))
                        # print("Comparing {} to {}".format(a[k],compare))
                        while(a[k] == compare):
                            match.append(variant[k - 1])
                            # print(match)
                            k -= 1
                            compare = [k]
                            compare.extend([1] * (m))
                            # print("Comparing {} to {}".format(a[k],compare))
                            start = k
                        matched = " ".join(reversed(match))
                        # print("Variant:")
                        # pprint(variant)
                        # print("Start: {} End: {}".format(start,end))
                        substitutedvariant = variant[:start]
                        substitutedvariant.append(subvar)
                        substitutedvariant.extend(variant[end:])
                        # print("SubstitutedVariant: {}".format(substitutedvariant))
                        break
                if(len(matched)):
                    # print("Match: '{}' to '{}'".format(substitution, matched))
                    try:
                        variantscores[bestvariant]['matches'][substitution].append(matched)
                    except KeyError:
                        variantscores[bestvariant]['matches'][substitution] = [matched]
        # variantscores[bestvariant]['template']=besttemplate
        # pprint({
        #     self.intent_map['intents'][variantscores[bestvariant]['intent']]['name']: {
        #         'action': variantscores[bestvariant]['action'],
        #         'input': phrase,
        #         'matches': variantscores[bestvariant]['matches'],
        #         'score': variantscores[bestvariant]['score']
        #     }
        # })
        return {
            self.intent_map['intents'][variantscores[bestvariant]['intent']]['name']: {
                'action': variantscores[bestvariant]['action'],
                'input': phrase,
                'matches': variantscores[bestvariant]['matches'],
                'score': variantscores[bestvariant]['score']
            }
        }
