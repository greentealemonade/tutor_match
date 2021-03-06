from django.shortcuts import render
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views import generic
from django.contrib.auth.models import User
from .forms import PostForm, CommentForm, AcceptReportForm, AccuseForm, ReportForm, TutorReportForm, TutorSessionForm, TutorApplicationForm
from django.contrib.auth.decorators import login_required
from matching import models as matching_models
from django.db import transaction
from itertools import chain
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from matching.models import TOPIC_CHOICES
import json
from django.core.serializers.json import DjangoJSONEncoder
from django.views.generic.edit import UpdateView
from django.views.generic.detail import DetailView
from .models import Report
from django.utils import timezone
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.messages.views import SuccessMessageMixin
from django import forms
import datetime
from django.db.models import Count, Max, Sum, Subquery, OuterRef, F, Q, Min, Value, DateTimeField, CharField
#CSV import
from tablib import Dataset
import pandas
import magic, copy, csv

LOGIN_REDIRECT_URL = "/matching"
# DEFAULT PAGE

def login(request):
    if request.user.is_authenticated:
        return redirect('matching:mainpage', showtype='all')
    else:
        return render(request, 'matching/account_login.html', {})

def redirect_to_main(request):
    return redirect('matching:mainpage', showtype='all')


@login_required(login_url=LOGIN_REDIRECT_URL)
@transaction.atomic
def save_profile(request, pk):
    user = matching_models.User.objects.get(pk=pk)
    if not request.user.is_authenticated:
        return redirect('/accounts/login/')
    if request.method == 'POST':
        profile = user.profile
        profile.nickname = request.POST['nickname']
        profile.signin = True
        profile.phone = "010" + str(request.POST['phone1']) + str(request.POST['phone2'])
        profile.save()
        return redirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))
    return render(request, 'matching/save_profile.html', {'nickname': user.profile.nickname})

def user_check(request):
    if request.user.email.endswith('@handong.edu'):
        try:
            user = matching_models.User.objects.get(pk=request.user.pk)
            if user.profile.signin == False:
                user.profile.nickname =user.username[1:3] + user.last_name
                user.profile.signin = True
                user.profile.save()
                return HttpResponseRedirect(reverse('matching:profile', args=(request.user.pk,)))
            else:
                return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))
        except(KeyError, matching_models.User.DoesNotExist):
            return HttpResponseRedirect(reverse('matching:login'))
    else:
        messages.info(request, '한동 이메일로 로그인해주세요.')
        matching_models.User.objects.filter(pk=request.user.pk).delete()
        return HttpResponseRedirect(reverse('matching:login'))


@login_required(login_url=LOGIN_REDIRECT_URL)
def session_report_create(request, pk):
    try:
        session = get_object_or_404(matching_models.TutorSession, pk=pk)
    except:
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))
    user = matching_models.User.objects.get(username=request.user.username)

    if user != session.tutor:
        messages.add_message(request, messages.ERROR, '담당 튜터에게만 보고서 작성 권한이 있습니다.')
        return redirect('matching:mainpage', showtype='all')

    report_query = matching_models.Report.objects.filter(session=pk)
    if report_query.exists():
        return redirect('matching:mainpage', showtype='all')

    if request.method == "POST":
        form = TutorReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.tutor = user
            report.writer = user
            report.session = session
            report.content = form.cleaned_data['content']
            report.save()
            messages.add_message(request, messages.SUCCESS, '보고서가 제출되었습니다.')
            return redirect('matching:session_report_list', pk=pk)
    else:
        form = TutorReportForm()
    ctx = {'form' : form}
    return render(request, 'matching/session_report_create.html', ctx)


@login_required(login_url=LOGIN_REDIRECT_URL)
def tutee_report(request, pk):
    post = matching_models.Post.objects.get(pk=pk)
    if not (post.user == request.user or post.tutor == request.user):
        return redirect('matching:post_detail', pk=pk)

    report = matching_models.Report.objects.filter(post=pk, writer=request.user)
    if report.exists():
        return redirect('matching:post_detail', pk=pk)

    if request.method == "POST":
        if post.user == post.tutor:
            form = TutorReportForm(request.POST)
        else:
            form = ReportForm(request.POST)


        if form.is_valid():
            report = form.save(commit=False)
            if post.fin_time is None:
                fin_tutoring(request,pk)
            report.tutor = matching_models.User.objects.get(pk = post.tutor.pk)
            report.tutee = matching_models.User.objects.get(pk = post.user.pk)
            report.post = post
            report.writer = request.user
            report.save()
            profile = matching_models.Profile.objects.get(user = report.tutor)
            profile.tutor_tutoringTime += form.cleaned_data['duration_time']
            profile.save()
            return redirect('matching:report_detail', pk=report.pk)
        else:
            return redirect('matching:mainpage', showtype='all')

class ReportDetail(DetailView):
    model = Report

    def get(self, request, *args, **kwargs):
        report = matching_models.Report.objects.get(pk=self.kwargs['pk'])
        if self.request.user.is_staff or self.request.user == report.writer:
            return super(ReportDetail, self).get(request, *args, **kwargs)
        else:
            return redirect('matching:mainpage', showtype='all')

    def get_context_data(self, **kwargs):
        context = super(ReportDetail, self).get_context_data(**kwargs)
        context['form'] = AccuseForm
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = AccuseForm(request.POST, request.FILES)

        if form.is_valid():
            return self.form_valid(form, self.object)

    def form_valid(self, form, report):
        report.tutee_feedback = form.cleaned_data['tutee_feedback']
        report.save()

def post_report_list(request, pk):
    post = matching_models.Post.objects.get(pk=pk)
    report_list = matching_models.Report.objects.filter(post=post)
    tutor_report = matching_models.Report.objects.filter(writer=post.tutor)
    tutee_report = matching_models.Report.objects.filter(writer=post.user)

    ctx = {
        'post' : post,
        'report_list' : report_list,
        'tutor_report' : tutor_report,
        'tutee_report' : tutee_report,
    }

    return render(request, 'matching/report_list.html', ctx)

def session_report_list(request, pk):
    session = matching_models.TutorSession.objects.get(pk=pk)
    report_list = None
    ctx = {'session': session}
    if request.user.is_staff:
        report_list = matching_models.Report.objects.filter(session=session)
    elif request.user == session.tutor:
        report_list = matching_models.Report.objects.filter(session=session, writer=session.tutor)
    else:
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))
    ctx['report_list'] = report_list
    return render(request, 'matching/session_report_list.html', ctx)




@login_required(login_url=LOGIN_REDIRECT_URL)
def post_new(request):
    if request.method == "POST":
        form = PostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            user_obj = matching_models.User.objects.get(username=request.user.username)
            post.user = user_obj
            post.pub_date = timezone.localtime(timezone.now())
            post.finding_match = True
            post.save()

            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'new_post',
                {
                    'type': 'new_post',
                    'id': post.pk,
                    'title': post.title,
                    'finding': post.finding_match,
                    'pub_date': json.dumps(post.pub_date, cls=DjangoJSONEncoder),
                    #'topic': dict(TOPIC_CHOICES).get(post.topic),
                    'nickname': post.user.profile.nickname,
                }
            )

            return redirect('matching:post_detail', pk=post.pk)
    else:
        form = PostForm()


    ctx['form'] = form

    return render(request, 'matching/post_new.html', ctx)


@login_required(login_url=LOGIN_REDIRECT_URL)
def post_detail(request, pk):
    ctx={}

    try:
        post = get_object_or_404(matching_models.Post, pk=pk)
    except matching_models.Post.DoesNotExist:
        return HttpResponse("게시물이 존재하지 않습니다.")
    except:
        messages.error(request, '해당 방은 존재하지 않습니다.')
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

    if post.finding_match:
        pass
    elif post.start_time and not post.fin_time:
        pass
    else:
        if not request.user == post.user and not request.user == post.tutor and not request.user.is_staff:
            messages.error(request, '해당 QnA는 이미 종료되었습니다.')
            return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))



    user = matching_models.User.objects.get(username=request.user.username)
    post = matching_models.Post.objects.get(pk=pk)
    my_report = matching_models.Report.objects.filter(writer=user, post=pk)
    if my_report.exists(): #사용자가 쓴 보고서 존재
        ctx['my_report'] = my_report[0]
    elif post.fin_time or ((request.user == post.user) and post.tutor):
        #사용자가 쓴 보고서 존재하지 않고 종료되었거나
        if post.tutor == post.user:
            report_form = TutorReportForm()
        else:
            report_form = ReportForm()
        ctx['report_form'] = report_form
        ctx['report_exist'] = True

    comment_list = matching_models.Comment.objects.filter(post=post).order_by('pub_date')

    ctx['post'] = post
    ctx['comment_list'] = comment_list
    ctx['start_msg'] = "튜터링시작"+str(post.pub_date)
    ctx['cancel_msg'] = "튜터링취소"+str(post.pub_date)
    ctx['fin_msg'] = "튜터링종료"+str(post.pub_date)
    ctx['user_compare_msg'] = user.profile.nickname + '에게 답장'
    post.hit = post.hit + 1
    post.save()
    return render(request, 'matching/post_detail.html', ctx)



def set_tutor(request, postpk, userpk):
    post = matching_models.Post.objects.filter(tutor=request.user, fin_time__isnull=True)
    if post:
        # 튜터가 하나 이상의 튜터링을 동시에 진행할 수 없음
        messages.error(request, '이미 진행하고 있는 튜터링이 있습니다.')
        return redirect('matching:post_detail', pk=postpk)

    try:
        post = get_object_or_404(matching_models.Post, pk=postpk)
    except post.DoesNotExist:
        return HttpResponse("포스트가 없습니다.")

    try:
        tutor = get_object_or_404(User, pk=userpk)
    except tutor.DoesNotExist:
        return HttpResponse("사용자가 없습니다.")

    # if tutor.pk == post.user.pk:
    #     #포스트 작성자가 직접 튜터가 될 수 없음.
    #     return redirect('matching:post_detail', pk=post.pk)

    if post.tutor:
        messages.error(request, '해당 방은 튜터링이 이미 진행중입니다.')
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))


    post.tutor = tutor
    post.finding_match = False
    post.start_time = timezone.localtime(timezone.now())
    post.save()

    start_tutoring_cmt = matching_models.Comment(user=tutor, post=post, pub_date=timezone.now(), content="튜터링시작"+str(post.pub_date))
    start_tutoring_cmt.save()

    context = {
      'start_tutoring_cmt_pk' : start_tutoring_cmt.pk
    }

    return HttpResponse(json.dumps(context), content_type="application/json")

@login_required
def send_message(request):
    if request.method == "GET":
        if request.GET['type'] == "session":
          session = matching_models.TutorSession.objects.get(pk = request.GET['postid'])

          content = request.GET['content']
          reply_to = request.GET.get('reply_to')
          reply_content = request.GET.get('reply_content')

          response = {}
          if reply_to and reply_content:
              new_cmt = matching_models.Comment(user=request.user, tutorsession=session, pub_date=timezone.localtime(timezone.now()), content=content, reply_to=reply_to, reply_content=reply_content)
              response['reply_to'] = reply_to
              response['reply_content'] = reply_content
              new_cmt.save()
          else:
              new_cmt = matching_models.Comment(user=request.user, tutorsession=session, pub_date=timezone.localtime(timezone.now()), content=content)
              new_cmt.save()

          response['id'] = new_cmt.id
          response['url'] = "https://" + request.get_host() + reverse('matching:session_detail', args=[session.pk])
          return HttpResponse(json.dumps(response), content_type="application/json")
        else:
          post = matching_models.Post.objects.get(pk=request.GET['postid'])
          content = request.GET['content']
          reply_to = request.GET.get('reply_to')
          reply_content = request.GET.get('reply_content')

          response = {}
          if reply_to and reply_content:
              new_cmt = matching_models.Comment(user=request.user, post=post, pub_date=timezone.localtime(timezone.now()), content=content, reply_to=reply_to, reply_content=reply_content)
              response['reply_to'] = reply_to
              response['reply_content'] = reply_content
              new_cmt.save()
          else:
              new_cmt = matching_models.Comment(user=request.user, post=post, pub_date=timezone.localtime(timezone.now()), content=content)
              new_cmt.save()

          response['id'] = new_cmt.id
          response['url'] = "https://" + request.get_host() + reverse('matching:post_detail', args=[post.pk])
          return HttpResponse(json.dumps(response), content_type="application/json")
    else:
        return HttpResponse('NOT A GET REQUEST')



@login_required(login_url=LOGIN_REDIRECT_URL)
def post_edit(request, pk):
    ctx={}
    post = matching_models.Post.objects.get(pk=pk)

    if post.user.pk != request.user.pk:
        return redirect('matching:post_detail', pk=post.pk)

    form = PostForm(request.POST)
    if request.method == "POST":
        if form.is_valid():
            #post.topic = form.cleaned_data['topic']
            post.title = form.cleaned_data['title']
            post.save()
            return redirect('matching:post_detail', pk=post.pk)
    else:
        ctx['post'] = post

    return render(request, 'matching/post_edit.html', ctx)




@login_required(login_url=LOGIN_REDIRECT_URL)
@staff_member_required
def admin_home(request):
    tutorList = matching_models.User.objects.filter(profile__is_tutor=True)
    tutorDict = tutorList.values()

    for tutor in tutorDict:
        totalTutoringTime = 0
        tutor['nickname'] = matching_models.Profile.objects.filter(id=tutor['id']).get().nickname
        sessionList = matching_models.TutorSession.objects.filter(tutor_id=tutor['id'])
        tutoringList = matching_models.Post.objects.filter(tutor_id=tutor['id'], fin_time__isnull=False)
        tutoring_minutes = 0
        QnA_minutes = 0

        # 튜터세션별 진행시간 합하기
        for session in sessionList:
            logList = matching_models.SessionLog.objects.filter(tutor_session_id=session.id, fin_time__isnull=False, is_no_show=False)
            for log in logList:
                time_diff = log.fin_time - log.start_time
                tutoring_minutes += min(time_diff.seconds//60, 20)
                

        # Q&A별로 진행시간 합하기
        for tutoring in tutoringList:
            time_diff = tutoring.fin_time - tutoring.start_time
            QnA_minutes += (time_diff.seconds//60)

        tutor['TutoringTime'] = '{0}'.format(str(tutoring_minutes))
        tutor['QnATime'] = '{0}'.format(str(QnA_minutes))

    current_post_page = request.GET.get('page', 1)
    tutor_paginator = Paginator(tutorList, 10)
    try:
        tutorList = tutor_paginator.page(current_post_page)
    except PageNotAnInteger:
        tutorList = tutor_paginator.page(1)
    except EmptyPage:
        tutorList = tutor_paginator.page(tutor_paginator.num_pages)

    neighbors = 10
    if tutor_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, tutor_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > tutor_paginator.num_pages:
            start_index -= end_index - tutor_paginator.num_pages
            end_index = tutor_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, tutor_paginator.num_pages+1)

    ctx = {
        'tutorList': tutorDict,
        'tutorPaginator': tutor_paginator,
        'paginatorRange': paginatorRange
    }


    return render(request, 'matching/admin_tutor_list.html', ctx)


@login_required(login_url=LOGIN_REDIRECT_URL)
@staff_member_required
def csv_export(request):
    tutorList = matching_models.User.objects.filter(profile__is_tutor=True)
    tutorDict = tutorList.values()

    response = HttpResponse(content_type = 'text/csv')
    response['Content-Disposition'] = 'attachment; filename="student_final.csv"'
    writer = csv.writer(response, delimiter=',')
    writer.writerow(['이름', '학번', '응대횟수', '응대시간(분)'])

    for tutor in tutorDict:
        totalTutoringTime = 0
        tutor['nickname'] = matching_models.Profile.objects.filter(id=tutor['id']).get().nickname
        tutor['username'] = matching_models.User.objects.filter(id=tutor['id']).get().username
        sessionList = matching_models.TutorSession.objects.filter(tutor_id=tutor['id'])
        tutoringList = matching_models.Post.objects.filter(tutor_id=tutor['id'], fin_time__isnull=False)
        tutoring_minutes = 0
        QnA_minutes = 0

        # 튜터세션별 진행시간 합하기
        cnt = 0
        for session in sessionList:
            logList = matching_models.SessionLog.objects.filter(tutor_session_id=session.id, fin_time__isnull=False, is_no_show=False)
            cnt += len(logList)
            for log in logList:
                time_diff = log.fin_time - log.start_time
                tutoring_minutes += min((time_diff.seconds//60), 20)

        writer.writerow([tutor['nickname'], tutor['username'], cnt, tutoring_minutes])

    return response



@login_required(login_url=LOGIN_REDIRECT_URL)
@staff_member_required
def admin_session_list(request):
    session_list = matching_models.TutorSession.objects.all().order_by('-start_time').annotate()
    log_list = matching_models.SessionLog.objects.all()

    session_dict = session_list.values()

    for session in session_dict:
        session_obj = session_list.get(pk=session['id'])
        session['tutor'] = session_obj.tutor.profile.nickname
        finished_logs = log_list.filter(tutor_session_id=session['id'], start_time__isnull=False, fin_time__isnull=False, is_no_show=False)
        total_num_tutoring = finished_logs.count()
        no_show_logs = log_list.filter(tutor_session_id=session['id'], start_time__isnull=False, fin_time__isnull=False, is_no_show=True)
        no_show_cnt = no_show_logs.count()

        total_tutoring_time = 0
        hours = 0
        minutes = 0

        for log in finished_logs:
            time_diff = log.fin_time - log.start_time
            hours += time_diff.seconds//3600
            minutes += time_diff.seconds//60%60

        hours += minutes // 60
        minutes = minutes % 60

        session['total_num_tutoring'] = total_num_tutoring
        session['total_tutoring_time'] = '{0}시간 {1}분'.format(str(hours),str(minutes))
        session['no_show_cnt'] = no_show_cnt

    current_post_page = request.GET.get('page', 1)
    session_paginator = Paginator(session_list, 10)
    try:
        session_list = session_paginator.page(current_post_page)
    except PageNotAnInteger:
        session_list = session_paginator.page(1)
    except EmptyPage:
        session_list = session_paginator.page(session_paginator.num_pages)

    neighbors = 10
    if session_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, session_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > session_paginator.num_pages:
            start_index -= end_index - session_paginator.num_pages
            end_index = session_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, session_paginator.num_pages+1)

    ctx = {
        'sessionlist': session_dict,
        'sessionPaginator': session_paginator,
        'paginatorRange': paginatorRange,
    }


    return render(request, 'matching/admin_session_list.html', ctx)


@login_required(login_url=LOGIN_REDIRECT_URL)
@staff_member_required
def session_log_detail(request, session_pk):
    session = matching_models.TutorSession.objects.get(pk=session_pk)

    loglist = matching_models.SessionLog.objects.filter(tutor_session=session)

    current_post_page = request.GET.get('page', 1)
    log_paginator = Paginator(loglist, 10)
    try:
        loglist = log_paginator.page(current_post_page)
    except PageNotAnInteger:
        loglist = log_paginator.page(1)
    except EmptyPage:
        loglist = log_paginator.page(log_paginator.num_pages)

    neighbors = 10
    if log_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, log_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > log_paginator.num_pages:
            start_index -= end_index - log_paginator.num_pages
            end_index = log_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, log_paginator.num_pages+1)

    ctx = {
        'loglist': loglist,
        'logPaginator': log_paginator,
        'paginatorRange': paginatorRange,
    }


    return render(request, 'matching/session_log_detail.html', ctx)



@login_required(login_url=LOGIN_REDIRECT_URL)
@staff_member_required
def tutee_list(request):

    tutee_list = matching_models.User.objects.all().annotate(
        num_posts = Count('post_relation')
    )

    current_post_page = request.GET.get('page', 1)
    tutee_paginator = Paginator(tutee_list, 10)
    try:
        tutee_list = tutee_paginator.page(current_post_page)
    except PageNotAnInteger:
        tutee_list = tutee_paginator.page(1)
    except EmptyPage:
        tutee_list = tutee_paginator.page(tutee_paginator.num_pages)

    neighbors = 10
    if tutee_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, tutee_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > tutee_paginator.num_pages:
            start_index -= end_index - tutee_paginator.num_pages
            end_index = tutee_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, tutee_paginator.num_pages+1)

    ctx = {
        'tutee_list': tutee_list,
        'tuteePaginator': tutee_paginator,
        'paginatorRange': paginatorRange,
    }

    return render(request, 'matching/admin_tutee_list.html', ctx)

@staff_member_required
def userlist(request):
    search_word = request.GET.get('search_word', '')
    if search_word != '':
        userlist = matching_models.User.objects.filter(Q(profile__nickname__icontains=search_word) | Q(email__icontains=search_word))
    else:
        userlist = matching_models.User.objects.all()


    current_post_page = request.GET.get('page', 1)
    user_paginator = Paginator(userlist, 10)
    try:
        userlist = user_paginator.page(current_post_page)
    except PageNotAnInteger:
        userlist = user_paginator.page(1)
    except EmptyPage:
        userlist = user_paginator.page(user_paginator.num_pages)

    neighbors = 10
    if user_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, user_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > user_paginator.num_pages:
            start_index -= end_index - user_paginator.num_pages
            end_index = user_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, user_paginator.num_pages+1)

    ctx = {
        'userlist': userlist,
        'userPaginator': user_paginator,
        'paginatorRange': paginatorRange,
    }

    if search_word != '':
        ctx['search_word'] = search_word

    return render(request, 'matching/admin_user_list.html', ctx)

@staff_member_required
def apply_list(request):
    applylist = matching_models.TutorApplication.objects.all().exclude(user__profile__is_tutor=True)

    current_post_page = request.GET.get('page', 1)
    apply_paginator = Paginator(applylist, 10)
    try:
        applylist = apply_paginator.page(current_post_page)
    except PageNotAnInteger:
        applylist = apply_paginator.page(1)
    except EmptyPage:
        applylist = apply_paginator.page(apply_paginator.num_pages)

    neighbors = 10
    if apply_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, apply_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > apply_paginator.num_pages:
            start_index -= end_index - apply_paginator.num_pages
            end_index = apply_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, apply_paginator.num_pages+1)

    ctx = {
        'applylist': applylist,
        'applyPaginator': apply_paginator,
        'paginatorRange': paginatorRange,
    }


    return render(request, 'matching/admin_apply_list.html', ctx)

@staff_member_required
def make_tutor(request, pk):
    user = matching_models.User.objects.get(pk=pk)
    matching_models.TutorApplication.objects.filter(user=user).delete()
    userinfo = matching_models.Profile.objects.get(user=user)
    userinfo.is_tutor = True
    userinfo.save()

    return redirect(reverse('matching:userlist'))

@staff_member_required
def remove_application(request, pk):
    user = matching_models.User.objects.get(pk=pk)
    matching_models.TutorApplication.objects.get(user=user).delete()

    return redirect(reverse('matching:apply_list'))

@staff_member_required
def remove_tutor(request, pk):
    user = matching_models.User.objects.get(pk=pk)
    userinfo = matching_models.Profile.objects.get(user=user)
    userinfo.is_tutor = False
    userinfo.save()

    return redirect(reverse('matching:userlist'))

@staff_member_required
def make_staff(request, pk):
    user = matching_models.User.objects.get(pk=pk)
    user.is_staff = True
    user.save()

    return redirect(reverse('matching:userlist'))

@staff_member_required
def remove_staff(request, pk):
    user = matching_models.User.objects.get(pk=pk)
    user.is_staff = False
    user.save()

    return redirect(reverse('matching:userlist'))

@login_required(login_url=LOGIN_REDIRECT_URL)
def tutor_detail(request, pk):
    if not request.user.is_staff:
        return redirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

    tutor = matching_models.User.objects.get(pk=pk)
    postlist = matching_models.Post.objects.filter(tutor=tutor).order_by('-pub_date')
    sessionlist = matching_models.TutorSession.objects.filter(tutor=tutor).order_by('-pub_date')

    ctx = {
        'today' : timezone.localtime(timezone.now()),
        'tutor' : tutor,
        'postlist' : postlist,
        'sessionlist' : sessionlist,
    }

    return render(request, 'matching/tutor_detail.html', ctx)

@login_required(login_url=LOGIN_REDIRECT_URL)
def tutee_detail(request, pk):
    if not request.user.is_staff:
        return redirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

    tutee = matching_models.User.objects.get(pk=pk)
    postlist = matching_models.Post.objects.filter(user=tutee)

    ctx = {
        'today' : timezone.localtime(timezone.now()),
        'tutee' : tutee,
        'postlist' : postlist,
    }

    return render(request, 'matching/tutee_detail.html', ctx)

# Tutee가 끝낼 때
def close_post(request, pk):
    post = matching_models.Post.objects.get(pk=pk)
    post.finding_match = False
    post.save()
    return redirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

# Tutor가 끝낼 때
def fin_tutoring(request, pk):
    post = matching_models.Post.objects.get(pk=pk)
    post.fin_time = timezone.localtime(timezone.now())
    post.save()
    fin_tutoring_cmt = matching_models.Comment(user=post.tutor, post=post, pub_date=timezone.now(), content="튜터링종료"+str(post.pub_date))
    fin_tutoring_cmt.save()

    return redirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

# Tutor가 끝낼 때
def fin_tutoring_realTime(request, pk):
    post = matching_models.Post.objects.get(pk=pk)
    post.fin_time = timezone.localtime(timezone.now())
    post.save()
    fin_tutoring_cmt = matching_models.Comment(user=post.tutor, post=post, pub_date=timezone.now(), content="튜터링종료"+str(post.pub_date))
    fin_tutoring_cmt.save()

    context = {
      'finish_tutoring_cmt_pk' : fin_tutoring_cmt.pk,
      'mainpage_url': "https://" + request.get_host() + reverse('matching:mainpage', kwargs={'showtype':'all'})
    }

    return HttpResponse(json.dumps(context), content_type="application/json")

# Tutor가 튜터링 중도 취소
def cancel_tutoring_realTime(request, pk):
    post = matching_models.Post.objects.get(pk=pk)

    cancel_tutoring_cmt = matching_models.Comment(user=post.tutor, post=post, pub_date=timezone.now(), content="튜터링취소"+str(post.pub_date))
    cancel_tutoring_cmt.save()

    post.tutor = None
    post.finding_match = True
    post.start_time = None
    post.save()

    context = {
      'cancel_tutoring_cmt_pk' : cancel_tutoring_cmt.pk,
      'mainpage_url': "https://" + request.get_host() + reverse('matching:mainpage', kwargs={'showtype':'all'})
    }

    return HttpResponse(json.dumps(context), content_type="application/json")

def cancel_tutoring(request, pk):
    post = matching_models.Post.objects.get(pk=pk)

    cancel_tutoring_cmt = matching_models.Comment(user=post.tutor, post=post, pub_date=timezone.now(), content="튜터링취소"+str(post.pub_date))
    cancel_tutoring_cmt.save()

    post.tutor = None
    post.finding_match = True
    post.start_time = None
    post.save()

    return redirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))


@login_required(login_url=LOGIN_REDIRECT_URL)
def mypage(request):
    ctx = {}
    if request.user.profile.is_tutor:
        return redirect(reverse('matching:mypage_tutor_session'))
    return redirect(reverse('matching:mypage_post'))

class ProfileUpdateView(SuccessMessageMixin, UpdateView):
    model = matching_models.Profile
    fields = ['nickname']
    context_object_name = 'profile'
    template_name = 'matching/mypage_profile_update.html'
    success_message = '닉네임이 %(nickname)s 으로 수정되었습니다.'

    def get_object(self):
        profile = get_object_or_404(matching_models.Profile, pk=self.kwargs['pk'])
        return profile

    def get_form(self, form_class=None):
        if form_class is None:
            form_class = self.get_form_class()
        form = super(ProfileUpdateView, self).get_form(form_class)
        form.fields['nickname'].widget = forms.TextInput(attrs={'placeholder':'학번+이름 (예:20김튜티)', 'size':30})
        return form

    def get_success_url(self):
        return reverse('matching:mypage_profile', kwargs={'pk':self.object.pk})


@login_required(login_url=LOGIN_REDIRECT_URL)
def mypage_post(request):
    ctx = {}
    post = matching_models.Post.objects.filter(user=request.user)

    recruiting = post.filter(finding_match = True).order_by('-pub_date')
    onprocess = post.filter(start_time__isnull = False, fin_time__isnull = True).order_by('-pub_date')
    recruited = post.filter(finding_match = False).order_by('-pub_date')
    recruited = recruited.exclude(start_time__isnull = False, fin_time__isnull = True)
    #posts = tutor_models.Post.objects.order_by('-pub_date')
    posts = list(chain(recruiting, onprocess, recruited))


    if request.method == "POST":
        form = TutorApplicationForm(request.POST)

        if form.is_valid():
            application = form.save(commit=False)

            prev = matching_models.TutorApplication.objects.filter(user=request.user)
            if prev.exists():
                messages.error(request, '이미 튜터 신청을 했습니다. ')
                return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

            application.user = request.user
            application.date = timezone.localtime(timezone.now())
            application.save()

            name = request.user.profile.nickname
            url = "https://" + request.get_host() + reverse('matching:apply_list')
            payload = '{"body":"' + name + '","connectColor":"#6C639C","connectInfo":[{"imageUrl":"' + url + '"}]}'

            headers = {'Accept': 'application/vnd.tosslab.jandi-v2+json',
            'Content-Type': 'application/json'}

            r = requests.post("https://wh.jandi.com/connect-api/webhook/20949533/ee62d73c8d858690d41a1f51f63c7800", data=payload.encode('utf-8'), headers=headers)

            return redirect('matching:mypage_post')
    else:
        form = TutorApplicationForm()


    current_post_page = request.GET.get('page', 1)

    post_paginator = Paginator(posts, 10)
    try:
        posts = post_paginator.page(current_post_page)
    except PageNotAnInteger:
        posts = post_paginator.page(1)
    except EmptyPage:
        posts = post_paginator.page(post_paginator.num_pages)

    neighbors = 10
    if post_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, post_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > post_paginator.num_pages:
            start_index -= end_index - post_paginator.num_pages
            end_index = post_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, post_paginator.num_pages+1)

    ctx = {
        'posts' : posts,
        'postPaginator': post_paginator,
        'paginatorRange': paginatorRange,
        'form' : form,
    }

    return render(request, 'matching/mypage_post.html', ctx)

@login_required(login_url=LOGIN_REDIRECT_URL)
def mypage_tutee_session(request):
    ctx = {}

    posts = matching_models.SessionLog.objects.filter(tutee_id=request.user.pk, start_time__isnull=False, fin_time__isnull=False)

    current_post_page = request.GET.get('page', 1)

    post_paginator = Paginator(posts, 10)
    try:
        posts = post_paginator.page(current_post_page)
    except PageNotAnInteger:
        posts = post_paginator.page(1)
    except EmptyPage:
        posts = post_paginator.page(post_paginator.num_pages)

    neighbors = 10
    if post_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, post_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > post_paginator.num_pages:
            start_index -= end_index - post_paginator.num_pages
            end_index = post_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, post_paginator.num_pages+1)

    ctx = {
        'posts' : posts,
        'postPaginator': post_paginator,
        'paginatorRange': paginatorRange,
    }

    return render(request, 'matching/mypage_tutee_session.html', ctx)

@login_required(login_url=LOGIN_REDIRECT_URL)
def mypage_session(request):
    ctx = {}

    session_list = matching_models.TutorSession.objects.filter(tutor=request.user).order_by('-pub_date')
    log_list = matching_models.SessionLog.objects.all()

    session_dict = session_list.values()

    for session in session_dict:
        session_obj = session_list.get(pk=session['id'])
        finished_logs = log_list.filter(tutor_session_id=session['id'], fin_time__isnull=False)
        total_num_tutoring = finished_logs.count()
        no_show_logs = log_list.filter(tutor_session_id=session['id'], is_no_show=True)
        no_show_cnt = no_show_logs.count()

        total_tutoring_time = 0
        for log in finished_logs:
            fin_time = log.fin_time
            start_time = log.start_time
            time_diff = fin_time - start_time
            time_diff_min = time_diff.seconds //60
            total_tutoring_time += time_diff_min

        session['total_num_tutoring'] = total_num_tutoring
        session['total_tutoring_time'] = total_tutoring_time
        session['no_show_cnt'] = no_show_cnt
        #session.save()

    current_session_page = request.GET.get('page', 1)
    session_paginator = Paginator(session_list, 10)
    try:
        sessions = session_paginator.page(current_session_page)
    except PageNotAnInteger:
        sessions = session_paginator.page(1)
    except EmptyPage:
        sessions = session_paginator.page(session_paginator.num_pages)

    neighbors = 10
    if session_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_session_page)-neighbors)
        end_index = min(int(current_session_page)+neighbors, session_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > session_paginator.num_pages:
            start_index -= end_index - session_paginator.num_pages
            end_index = session_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, session_paginator.num_pages+1)

    ctx = {
        'sessions': session_dict,
        'sessionPaginator': session_paginator,
        'paginatorRange': paginatorRange,
        'today': timezone.localtime(timezone.now()),
    }

    return render(request, 'matching/mypage_session.html', ctx)


@login_required(login_url=LOGIN_REDIRECT_URL)
def mypage_tutor_post(request):
    ctx = {}
    post = matching_models.Post.objects.filter(tutor=request.user)

    recruiting = post.filter(finding_match = True).order_by('-pub_date')
    onprocess = post.filter(start_time__isnull = False, fin_time__isnull = True).order_by('-pub_date')
    recruited = post.filter(finding_match = False).order_by('-pub_date')
    recruited = recruited.exclude(start_time__isnull = False, fin_time__isnull = True)
    #posts = tutor_models.Post.objects.order_by('-pub_date')
    posts = list(chain(recruiting, onprocess, recruited))

    current_post_page = request.GET.get('page', 1)

    post_paginator = Paginator(posts, 10)
    try:
        posts = post_paginator.page(current_post_page)
    except PageNotAnInteger:
        posts = post_paginator.page(1)
    except EmptyPage:
        posts = post_paginator.page(post_paginator.num_pages)

    neighbors = 10
    if post_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, post_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > post_paginator.num_pages:
            start_index -= end_index - post_paginator.num_pages
            end_index = post_paginator.num_pages
        paginatorRange = [f for f in range(start_index, end_index+1)]
        paginatorRange[:(2*neighbors + 1)]
    else:
        paginatorRange = range(1, post_paginator.num_pages+1)

    ctx = {
        'posts' : posts,
        'postPaginator': post_paginator,
        'paginatorRange': paginatorRange,
    }
    return render(request, 'matching/mypage_tutor_post.html', ctx)

import requests, datetime
@login_required(login_url=LOGIN_REDIRECT_URL)
def mainpage(request, showtype):
    post = matching_models.Post.objects.filter(user = request.user, finding_match = True)
    post_exist = False

    if post:
        post_exist = True

    user = matching_models.User.objects.get(pk=request.user.pk)
    now = timezone.localtime(timezone.now())

    ongoing_session = matching_models.TutorSession.objects.filter(tutor=user, start_time__lte=now).filter(fin_time__isnull=True)
    if ongoing_session.exists():
        ongoing_session = ongoing_session[:1].get()

    ongoing_tutoring = matching_models.Post.objects.filter(tutor=user).filter(fin_time__isnull=True)
    if ongoing_tutoring.exists():
        ongoing_tutoring = ongoing_tutoring[:1].get()

    ongoing_post = matching_models.Post.objects.filter(user=user).filter(finding_match=True)
    if ongoing_post.exists():
        ongoing_post = ongoing_post[:1].get()

    if request.method == "POST":
        tsform = TutorSessionForm(request.POST)
        form = PostForm(request.POST)
        check_post_exist = matching_models.Post.objects.filter(user = request.user, finding_match = True)

        if tsform.is_valid():
            tutorsession = tsform.save(commit=False)
            if tutorsession.expected_fin_time < tutorsession.start_time:
                messages.error(request, '튜터링 종료 시간이 시작 시간보다 후여야 합니다.')
                return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))
            user_obj = matching_models.User.objects.get(username=request.user.username)
            tutorsession.tutor = user_obj
            tutorsession.pub_date = timezone.localtime(timezone.now())
            tutorsession.save()

            return redirect('matching:session_detail', pk=tutorsession.pk)

        elif form.is_valid() and not check_post_exist:
            post = form.save(commit=False)
            user_obj = matching_models.User.objects.get(username=request.user.username)
            post.user = user_obj
            post.pub_date = timezone.localtime(timezone.now())
            post.finding_match = True
            post.save()

            try:
              post.report.exists()
              reportExist = True
            except:
              reportExist = False

            try:
              post.tutor.exists()
              tutorExist = True
            except:
              tutorExist = False

            '''
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'new_post',
                {
                    'type': 'new_post',
                    'id': post.pk,
                    'title': post.title,
                    'finding': post.finding_match,
                    'pub_date': json.dumps(post.pub_date, cls=DjangoJSONEncoder),
                    #'topic': dict(TOPIC_CHOICES).get(post.topic),
                    'nickname': post.user.profile.nickname,
                    'startTime': json.dumps(post.start_time, cls=DjangoJSONEncoder),
                    'endTime': json.dumps(post.fin_time, cls=DjangoJSONEncoder),
                    'postUser': post.user.pk,
                    'tutor': tutorExist,
                    'reportExist': reportExist,
                    'hit': post.hit,
                }
            )
            '''
            title = post.title
            url = "https://" + request.get_host() + reverse('matching:post_detail', args=[post.pk])
            payload = '{"body":"' + title + '","connectColor":"#6C639C","connectInfo":[{"imageUrl":"' + url + '"}]}'

            headers = {'Accept': 'application/vnd.tosslab.jandi-v2+json',
            'Content-Type': 'application/json'}

            #r = requests.post("https://wh.jandi.com/connect-api/webhook/20949533/4bbee5c811038e410ccea15513acd716", data=payload.encode('utf-8'), headers=headers)
            return redirect('matching:post_detail', pk=post.pk)
    else:
        form = PostForm()
        tsform = TutorSessionForm()


    search_word = request.GET.get('search_word', '') # GET request의 인자중에 q 값이 있으면 가져오고, 없으면 빈 문자열 넣기
    start = datetime.date.today()
    end = start + datetime.timedelta(days=1)
    start = start - datetime.timedelta(days=1)

    tutoring_on = matching_models.TutorSession.objects.filter(start_time__range=(start, end), fin_time__isnull=True)
    tutoring_before_start = matching_models.TutorSession.objects.exclude(id__in=tutoring_on).filter(start_time__gte=end).order_by('start_time')
    tutoring_others = matching_models.TutorSession.objects.exclude(id__in=tutoring_on).exclude(id__in=tutoring_before_start).order_by('-pub_date')
    tutoring_off = tutoring_before_start | tutoring_others
    #tutoring_off = matching_models.TutorSession.objects.exclude(id__in=tutoring_on).order_by('').order_by('-pub_date')
    recruiting = matching_models.Post.objects.filter(finding_match = True).order_by('-pub_date')
    onprocess = matching_models.Post.objects.filter(start_time__isnull = False, fin_time__isnull = True).order_by('-pub_date')
    recruited = matching_models.Post.objects.exclude(id__in=recruiting).exclude(id__in=onprocess).order_by('-pub_date')

    ### 튜터링 검색기능 ###
    if search_word != '':
        tutoring_on = tutoring_on.filter(title__icontains=search_word)
        tutoring_off = tutoring_off.filter(title__icontains=search_word)
        recruiting = recruiting.filter(title__icontains=search_word)
        onprocess = onprocess.filter(title__icontains=search_word)
        recruited = recruited.filter(title__icontains=search_word)

    if showtype == 'session':
        posts = list(chain(tutoring_on, tutoring_off))
    elif showtype == 'tutoring':
        posts = list(chain(recruiting, onprocess,recruited))
    elif showtype == 'all':
        posts = list(chain(tutoring_on, recruiting, onprocess, tutoring_off, recruited))
    else:
        return redirect('matching:mainpage', showtype='all')

    current_post_page = request.GET.get('page', 1)
    post_paginator = Paginator(posts, 9)
    try:
        posts = post_paginator.page(current_post_page)
    except PageNotAnInteger:
        posts = post_paginator.page(1)
    except EmptyPage:
        posts = post_paginator.page(post_paginator.num_pages)


    neighbors = 10
    if post_paginator.num_pages > 2*neighbors:
        start_index = max(1, int(current_post_page)-neighbors)
        end_index = min(int(current_post_page)+neighbors, post_paginator.num_pages)
        if end_index < start_index + 2*neighbors:
            end_index = start_index + 2*neighbors
        elif start_index > end_index - 2*neighbors:
            start_index = end_index - 2*neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > post_paginator.num_pages:
            start_index -= end_index - post_paginator.num_pages
            end_index = post_paginator.num_pages
        paginator_range = [f for f in range(start_index, end_index+1)]
        paginator_range[:(2*neighbors + 1)]
    else:
        paginator_range = range(1, post_paginator.num_pages+1)


    ctx = {
        'ongoing_session' : ongoing_session,
        'ongoing_tutoring' : ongoing_tutoring,
        'ongoing_post': ongoing_post,
        'user': user,
        'posts': posts,
        'postPaginator': post_paginator,
        'paginatorRange': paginator_range,
        'form': form,
        'tsform': tsform,
        'post_exist': post_exist,
        'today' : timezone.localtime(timezone.now()),
    }

    # main.html에서 튜티도 진행중인 튜터링이 보이게 하기
    if not user.profile.is_tutor:
        try :
            ongoing_tutoring_tutee = matching_models.Post.objects.get(user=user, tutor__isnull=False, start_time__isnull=False, fin_time__isnull=True)
            ctx['ongoing_tutoring_tutee'] = ongoing_tutoring_tutee
        except matching_models.Post.DoesNotExist :
            ongoing_tutoring_tutee = None


    # Tutor Report Part
    user_obj2 = matching_models.User.objects.get(username=request.user.username)
    report_to_write = matching_models.Post.objects.filter(tutor=user_obj2, tutor__isnull=False).exclude(report__writer=user_obj2)
    if report_to_write.exists():
        for report in report_to_write:
            if report.tutor == report.user:
                report_form = TutorReportForm()
            else:
                report_form = ReportForm()
            ctx['report_form'] = report_form
            ctx['report_post_pk'] = report.pk

            # Tutoring이 정상적으로 종료되었을 경우
            if report.fin_time:
                ctx['report_exist'] = True
                ctx['unwritten_report'] = report

    session_report_to_write = matching_models.TutorSession.objects.filter(tutor=user_obj2, fin_time__isnull=False).exclude(report__writer=user_obj2)
    if session_report_to_write.exists():
        for report in session_report_to_write:
            ctx['report_session_pk'] = report.pk

            # Tutoring이 정상적으로 종료되었을 경우
            if report.fin_time:
                ctx['session_report_exist'] = True
                ctx['unwritten_session_report'] = report

    time = timezone.localtime(timezone.now())
    ctx['time'] = time.strftime("%Y/%m/%d %H:%M")

    return render(request, 'matching/main.html', ctx)



@login_required(login_url=LOGIN_REDIRECT_URL)
def session_detail(request, pk):
    ctx={
        'today' : timezone.localtime(timezone.now()),
    }

    try:
        session = get_object_or_404(matching_models.TutorSession, pk=pk)
    except matching_models.TutorSession.DoesNotExist:
        return HttpResponse("게시물이 존재하지 않습니다.")
    except:
        messages.error(request, '해당 튜터세션은 존재하지 않습니다.')
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

    req_user = matching_models.User.objects.get(username=request.user.username)
    my_report = matching_models.Report.objects.filter(writer=request.user, session=pk)

    if my_report.exists(): #사용자가 쓴 보고서 존재
        ctx['my_report'] = my_report
        ctx['my_report_pk'] = my_report[0].pk


    if (request.user != session.tutor) and not request.user.is_staff:
        try:
            log = matching_models.SessionLog.objects.get(is_waiting=False, start_time__isnull=False, fin_time__isnull=True, tutee=req_user, tutor_session=session)
        except matching_models.SessionLog.DoesNotExist:
            return redirect('matching:waitingroom', pk=pk)

    try:
      current_tutee = matching_models.SessionLog.objects.filter(is_waiting=False, start_time__isnull=False, fin_time__isnull=True, tutor_session=session).earliest('start_time')
      ctx['current_tutee'] = current_tutee
    except matching_models.SessionLog.DoesNotExist:
      print("No ongoing tutee")

    comment_list = matching_models.Comment.objects.filter(tutorsession=session).order_by('pub_date')
    ctx['user_compare_msg'] = req_user.profile.nickname + '에게 답장'
    ctx['user'] = req_user

    ctx['session'] = session
    ctx['comment_list'] = comment_list
    ctx['start_msg'] = "튜터링시작" +str(session.pub_date)
    ctx['fin_msg'] = "튜터링종료" +str(session.pub_date)
    ctx['pk'] = pk
    ctx['request'] = request
    waitingList = matching_models.SessionLog.objects.filter(is_waiting=True, tutor_session=session)
    ctx['waiting_tutee'] = len(waitingList)
    ctx['isSessionTutor'] = req_user.profile.pk == session.tutor.profile.pk
    session.hit = session.hit + 1
    session.save()
    return render(request, 'matching/session_detail.html', ctx)

@login_required(login_url=LOGIN_REDIRECT_URL)
def end_session(request, pk):
    session = matching_models.TutorSession.objects.get(pk=pk)
    if request.user == session.tutor:
        session.fin_time = timezone.localtime(timezone.now())
        session.save()
        current_tutoring = matching_models.SessionLog.objects.filter(tutor_session=session, start_time__isnull=False, fin_time__isnull=True).update(fin_time=session.fin_time)
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
          'new_comment_session' + str(session.pk),
          {
            'type': 'end_session',
            'sessionPk': 'session.pk'
          }
        )

        return redirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))
    else:
        return redirect(reverse('matching:session_detail'), args=[pk])



@login_required(login_url=LOGIN_REDIRECT_URL)
def waitingroom(request, pk):
    user = matching_models.User.objects.get(username=request.user.username)

    try:
        session = get_object_or_404(matching_models.TutorSession, pk=pk)
    except:
        messages.error(request, '해당 튜터세션은 존재하지 않습니다.')
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))
    if session.fin_time :
        messages.error(request, '종료된 튜터세션에 참여하실 수 없습니다.')
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

    if user == session.tutor:
        return redirect('matching:session_detail', pk=pk)

    try: # 세션에서 튜터링 끝나지 않은 상태에서 다시 세션에 들어온 튜티 -> 바로 채팅방으로 보내야함.
        log = matching_models.SessionLog.objects.get(is_waiting=False, tutee=user, tutor_session=session, start_time__isnull=False, fin_time__isnull=True)
        return redirect('matching:session_detail', pk=session.pk)
    except matching_models.SessionLog.DoesNotExist:
      try:
        log = matching_models.SessionLog.objects.get(is_waiting=True, tutor_session = session, tutee = user)
        log.wait_time = timezone.localtime(timezone.now())
        log.save()
      except matching_models.SessionLog.DoesNotExist:
        log = matching_models.SessionLog.objects.create(tutor_session=session, tutee=user)
        log.save()

    waitingList = matching_models.SessionLog.objects.filter(is_waiting=True, tutor_session=session)
    waitingTutee = log

    ctx = {
        'session' : session,
        'user' : request.user,
        'waitingTutee' : waitingTutee,
        'pk' : pk,
        'tuteePk' : user.pk,
    }

    if waitingTutee:
        tuteeTurn = waitingTutee.ranking(session)
        totalWaiting = len(waitingList)
        waitingAfterTutee = totalWaiting - tuteeTurn

        if waitingAfterTutee == -1:
            waitingAfterTutee = 0

        ctx['waitingBeforeTutee'] = tuteeTurn - 1
        ctx['tuteeTurn'] = tuteeTurn
        ctx['waitingAfterTutee'] = waitingAfterTutee, # waitingAfterTutee is int, but ctx['...'] is tuple?
        ctx['totalWaiting'] = totalWaiting

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
          'new_comment_session' + str(session.pk),
          {
            'type': 'new_waiting_tutee',
            'new_tutee_turn': tuteeTurn,
            'waiting_tutee_pk': waitingTutee.pk,
          }
        )

    if session.start_time > timezone.localtime(timezone.now()):
      ctx['started'] = True

    return render(request, 'matching/waiting_room.html', ctx)

from django.views.decorators.http import require_POST

@login_required
@require_POST # 해당 뷰는 POST method 만 받는다.
def not_waiting(request):
    pk = request.POST.get('pk', None) # ajax 통신을 통해서 template에서 POST방식으로 전달
    log_pk = request.POST.get('log_pk', None)

    try:
        log = matching_models.SessionLog.objects.get(pk=log_pk)
    except matching_models.SessionLog.DoesNotExist:
        log = None

    if log:
        # log.wait_time = timezone.localtime(timezone.now())
        log.is_waiting = False
        log.save()

    context = {
       'message': "튜터링 대기열에서 제외되었습니다.",
    }

    return HttpResponse(json.dumps(context), content_type="application/json")
    # context를 json 타입으로

@login_required
@require_POST
def set_attending_type(request):
  pk = request.POST.get('pk', None)
  online = request.POST.get('online', None)

  session = matching_models.TutorSession.objects.get(pk=pk)

  try:
      log = matching_models.SessionLog.objects.get(tutee = request.user, tutor_session = session, is_waiting = True)
  except matching_models.SessionLog.DoesNotExist:
      log = None

  context = {}
  if log:
    if online == "true":
      log.attend_online = True
      log.save()
      context['message'] = "세션을 온라인으로 참석합니다."
    else:
      log.attend_online = False
      log.save()
      context['message'] = "세션을 오프라인으로 참석합니다."
  else:
    context['message'] = "로그가 존재하지 않습니다."

  return HttpResponse(json.dumps(context), content_type="application/json")

@login_required
@require_POST
def start_new_tutoring(request, pk):
  if request.method == 'POST':
    try:
        session = get_object_or_404(matching_models.TutorSession, pk=pk)
    except matching_models.TutorSession.DoesNotExist:
        return HttpResponse("게시물이 존재하지 않습니다.")
    except:
        messages.error(request, '해당 튜터세션은 존재하지 않습니다.')
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))

    context = {'session_pk' : session.pk}


    current_tutee = fin_current_tutee(request, session)
    next_tutee = get_next_tutee(request, session, request.user)

    if current_tutee :
      if request.POST['is_no_show'] == "True":
        current_tutee.is_no_show = True
        current_tutee.save()
      current_tutee_url = "https://" + request.get_host() + reverse('matching:mainpage', kwargs={'showtype':'all'})
      fin_tutoring_cmt = matching_models.Comment(user=current_tutee.tutee, tutorsession=session, pub_date=timezone.localtime(timezone.now()), content="튜터링종료"+str(session.pub_date))
      fin_tutoring_cmt.save()
      context['current_sessionLog_pk'] = current_tutee.pk
      context['current_tutee_url'] = current_tutee_url
    if next_tutee:
      next_tutee_url = "https://" + request.get_host() + reverse('matching:session_detail', args=[pk])
      start_tutoring_cmt = matching_models.Comment(user=next_tutee.tutee, tutorsession=session, pub_date=timezone.now(), content="튜터링시작"+str(session.pub_date))
      start_tutoring_cmt.save()
      context['next_sessionlog_pk'] = next_tutee.pk
      context['next_tutee_url'] = next_tutee_url

    return HttpResponse(json.dumps(context), content_type="application/json")


def get_next_tutee(request, session, req_user):
    # session log
    if session.tutor != req_user:
        messages.error(request, '해당 튜터만 새로운 튜터링을 시작할 수 있습니다.')
        return HttpResponseRedirect(reverse('matching:mainpage', kwargs={'showtype':'all'}))
    try:
        next_tutee = matching_models.SessionLog.objects.filter(tutor_session=session, is_waiting=True).earliest('wait_time')
    except matching_models.SessionLog.DoesNotExist:
        next_tutee = None

    if next_tutee:
        # Exception Handling 
        current_tutee = matching_models.SessionLog.objects.filter(is_waiting=False, start_time__isnull=False, fin_time__isnull=True, tutor_session=session)
        if current_tutee:
            for tutee in current_tutee:
                tutee.fin_time = timezone.localtime(timezone.now())
                tutee.save()
                
        next_tutee.start_time = timezone.localtime(timezone.now())
        next_tutee.is_waiting = False
        next_tutee.save()
    return next_tutee

def fin_current_tutee(request, session):
    try:
        current_tutee = matching_models.SessionLog.objects.filter(tutor_session=session, is_waiting=False, start_time__isnull=False, fin_time__isnull=True)
        for tutee in current_tutee: 
            tutee.fin_time = timezone.now()
            tutee.save()
    except:
        current_tutee = None
    return current_tutee


def guideline_main(request):
    return render(request, 'matching/histutor_guideline_main.html', {})

def guideline_announcement(request):
    return render(request, 'matching/announcement.html', {})

def tutor_guideline_kor(request):
    return render(request, 'matching/tutor_guideline_kor.html', {})

def tutor_guideline_eng(request):
    return render(request, 'matching/tutor_guideline_eng.html', {})

def tutee_guideline_kor(request):
    return render(request, 'matching/tutee_guideline_kor.html', {})

def tutee_guideline_eng(request):
    return render(request, 'matching/tutee_guideline_eng.html', {})
