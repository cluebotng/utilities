#!/usr/bin/env perl
use lib '/home/damianzaremba/software/perlmods/share/perl/5.10.1/';
# We want to know if stuff is going to explode in our face
use warnings;
use strict;

# Awesome logging
use Log::Log4perl;

# Wikipedia client
use MediaWiki::API;

# Mediawiki is too awesome to use unix time
use Date::Parse;
use Time::Local;

# Good for debugging
use Data::Dumper;

=head1 NAME
check_cluebotng.pl - A script to check cluebotng is running

=head1 OVERVIEW
This script checks the last edit time against a threashold.

=head1 AUTHOR
Damian Zaremba <damian@damianzaremba.co.uk>

=head1 LICENSE
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.

=head1 CONFIG

Hash of our config values

=head2 Required options

wiki_url - URL to the wiki api.php script
threashold - Time threashold
admins - Array of people to notify

=cut

# Config stuff
my $config = {
	wiki_url => "https://en.wikipedia.org/w/api.php",
	wiki_username => "DamianZaremba_Scripts",
	wiki_password => "don't steal my secrets :(",
	check_user => "ClueBot_III",
	threashold => 1800, # 15 min
	admins => [
		'damian@cluenet.org',
		'rich@cluenet.org',
	],
};

my $VERSION = "0.1";

# Stuff we need everywhere
our($logger);


=head1 METHODS

=head2 should_edit
Calculates if an edit should be performed (state has changed)

=head3 Arguments
Takes no arguments.

=head3 Returns
Returns nothing.

=cut

sub should_edit {
	my $wiki = shift;
	my $message = shift;
	$message =~ s/last edit was .+$//;

	my $ref = $wiki->get_page( { title => 'User:' . $config->{'check_user'} . '/running' } );
	unless ( $ref->{missing} ) {
                my $pmessage = $ref->{'*'};
                $pmessage =~ s/last edit was .+$//;

                if( $message eq $pmessage ) {
			return 0
		}
	}
	return 1
}

=head2 run
Sets up everything and kicks off the process.

=head3 Arguments
Takes no arguments.

=head3 Returns
Returns nothing.

=cut

sub run {
	# Setup the logger object
	Log::Log4perl->easy_init();
	$logger = Log::Log4perl->get_logger();

	# Error if we couldn't initialize the logger oject
	if( ! defined( $logger ) ) {
		print "!!! Could not init logger !!!\n";
		exit(1);
	}

	$logger->info("Connecting to wikipedia");
	my $wiki = MediaWiki::API->new();
	$wiki->{'config'}{'api_url'} = $config->{'wiki_url'};

	if(!$wiki->login({
		lgname => $config->{'wiki_username'},
		lgpassword => $config->{'wiki_password'},
	})) {
		$logger->error("Could not login to wikipedia: " . $wiki->{error}->{details});
		exit(1);
	}

	$logger->info("Getting user info");
	my $userinfo = $wiki->api({
		action => 'query',
		list => 'usercontribs',
		ucuser => $config->{'check_user'},
		'uclimit' => 1,
	});

	$logger->info("Got edit info");
	my $edit = $userinfo->{'query'}->{'usercontribs'}[0];
	my $editUNIXTime = str2time($edit->{'timestamp'});
	my $time = time();
	my $difference = $time-$editUNIXTime;

	$logger->info("Checking edit difference");
	if( $difference > $config->{'threashold'} ) {
		my $message = "Not running - last edit was " . $edit->{'title'} . " " . $difference . "s ago";
		$logger->info($message);

		if(should_edit($wiki, $message)) {
			if(!$wiki->edit({
				action => 'edit',
				title => 'User:' . $config->{'check_user'} . '/running',
				text => $message,
				summary => 'Bot not running',
			})) {
				$logger->error("Could not update the wiki");
			} else {
				$logger->info("Wiki updated");
			}
		} else {
			$logger->info("Not updating wiki");
		}
		notify_admins($message);
		exit(1);
	} else {
		$logger->info("Bot running - last edit was " . $edit->{'title'} . " " . $difference . "s ago");

		if(should_edit($wiki, 'Running')) {
			if(!$wiki->edit({
				action => 'edit',
				title => 'User:' . $config->{'check_user'} . '/running',
				text => 'Running',
				summary => 'Bot running',
			})) {
				$logger->error("Could not update the wiki");
			} else {
				$logger->info("Wiki updated");
			}
		} else {
			$logger->info("Not updating wiki");
		}
		exit(0);
	}
}

=head2 notify_admins
Emails the cluebotng admins if it doesn't appear to be editing

=head3 Arguments
message - Message to send

=head3 Returns
Returns nothing

=cut

sub notify_admins {
	my $message = shift;
	my $admins = join(", ", @{ $config->{"admins"} });

	$logger->info("Notifying admins: " . $admins);
	my $MAIL;
 	open($MAIL, "|/usr/lib/sendmail -oi -t");
	print $MAIL "From: watcher\@cluebot3\n";
	print $MAIL "To: " . $admins . "\n";
	print $MAIL "Subject: " . $config->{'check_user'} . " not running\n\n";
	print $MAIL "$message\n";
	close($MAIL)
}

run();