function [lindata,avebeta,avemu,avedisp,nu,xsi]=atavedata(ring,dpp,refpts,varargin)
%ATAVEDATA       Average of optical functions on selected elements
%
%[LINDATA,AVEBETA,AVEMU,AVEDISP,TUNES,CHROMS]=ATAVEDATA(RING,DPP,REFPTS)
%
%LINDATA : Identical to ATLINOPT output
%AVEBEA :  Average Beta functions
%AVEMU :   Average phase advance
%AVEDISP : Average dispersion
%TUNES : Vector of tunes
%CHROMS : Vector of chromaticites
%
%[LINDATA,AVEBETA,AVEMU,AVEDISP,TUNES,CHROMS]=ATAVEDATA(RING,DPP,REFPTS,ORBITIN)
%    does not search for closed orbit. instead ORBITIN is used


lr=length(ring)+1;
if islogical(refpts)
    refs=[refpts(:);false(lr-length(refpts),1)];
else
    refs=false(lr,1); % lr
    refs(refpts)=true;
end
long=atgetcells(ring,'Length',@(elem,lg) lg>0) & refs(1:end-1); %lr-1
needed=refs | [false;long]; %lr
[lind,nu,xsi]=atlinopt(ring,dpp,find(needed),varargin{:}); %needed

lindata=lind(refs(needed)); %refpts
avebeta=cat(1,lindata.beta); %refpts
avemu=cat(1,lindata.mu); %refpts
avedisp=cat(2,lindata.Dispersion)'; %refpts
ClosedOrbit=cat(2,lindata.ClosedOrbit)'; %refpts
%plot(avebeta);hold all;


if any(long)
    initial=[long(needed(1:end-1));false]; %needed
    final=[false;initial(1:end-1)]; %needed

    lg=initial(refs(needed)); % refpts
    L=atgetfieldvalues(ring(long),'Length'); %long
    
    beta0=avebeta(lg,:); %long
    alpha0=cat(1,lind(initial).alpha); %long
    mu0=avemu(lg,:); %long
    disp0=avedisp(lg,:); %long
    ClosedOrbit0=ClosedOrbit(lg,:); %long
    
    %beta1=cat(1,lind(final).beta); %long
    %alpha1=cat(1,lind(final).alpha); %long
    mu1=cat(1,lind(final).mu); %long
    disp1=cat(2,lind(final).Dispersion)'; %long
    ClosedOrbit1=cat(2,lind(final).ClosedOrbit)'; %long
    
    L2=[L L]; %long
    avebeta(lg,:)=betadrift(beta0,alpha0,L2);
    avemu(lg,:)=0.5*(mu0+mu1);
    avedisp(lg,[1 3])=(disp1(:,[1 3])+disp0(:,[1 3]))*0.5;

    foc=atgetcells(ring(long),'PolynomB',@(el,polb) length(polb)>=2 && polb(2)~=0||polb(3)~=0); %long
    if any(foc)
        qp=false(size(lg));
        qp(lg)=foc;
        K=zeros(size(L)); %long
        q=1e-12+atgetfieldvalues(ring(refpts(qp)),'PolynomB',{2});
        m=atgetfieldvalues(ring(refpts(qp)),'PolynomB',{3});
        R11=atgetfieldvalues(ring(refpts(qp)),'R2',{1,1});
        dx=(atgetfieldvalues(ring(refpts(qp)),'T2',{1})-atgetfieldvalues(ring(refpts(qp)),'T1',{1}))/2;
        ba=atgetfieldvalues(ring(refpts(qp)),'BendingAngle');
        ba(isnan(ba))=0;
        irho=ba./L(foc);
        e1=atgetfieldvalues(ring(refpts(qp)),'EntranceAngle');
        Fint=atgetfieldvalues(ring(refpts(qp)),'Fint');
        gap=atgetfieldvalues(ring(refpts(qp)),'gap');
        e1(isnan(e1))=0;
        Fint(isnan(Fint))=0;
        gap(isnan(gap))=0;
        d_csi=ba.*gap.*Fint.*(1+sin(e1).^2)./cos(e1)./L(foc);
        Cp=[ba.*tan(e1)./L(foc) -ba.*tan(e1-d_csi)./L(foc)];
        for ii=1:2
            alpha0(foc,ii)=alpha0(foc,ii)-beta0(foc,ii).*Cp(:,ii);
        end
        R11(isnan(R11))=1;
        irho(isnan(irho))=0;
        m(isnan(m))=0;
        dx(isnan(dx))=0;

        dx0=(ClosedOrbit0(foc,1)+ClosedOrbit1(foc,1))/2;
        K(foc)=q.*R11+2*m.*(dx0-dx);
        K2=[K -K]; %long
        K2(foc,1)=K2(foc,1)+irho.^2;
        sel=false(size(avebeta,1),1); %refpts
        sel(lg)=foc;
        avebeta(sel,:)=betafoc(beta0(foc,:),alpha0(foc,:),K2(foc,:),L2(foc,:));
        avedisp(sel,[1 3])=dispfoc(disp0(foc,[1 3]),disp0(foc,[2 4]),K2(foc,:),L2(foc,:));
    end
    avedisp(lg,[2 4])=(disp1(:,[1 3])-disp0(:,[1 3]))./L2;
end

    function avebeta=betadrift(beta0,alpha0,L)
        gamma0=(alpha0.*alpha0+1)./beta0;
        avebeta=beta0-alpha0.*L+gamma0.*L.*L/3;
    end

    function avebeta=betafoc(beta0,alpha0,K,L)
        gamma0=(alpha0.*alpha0+1)./beta0;
        avebeta=((beta0+gamma0./K).*L+(beta0-gamma0./K).*sin(2.0*sqrt(K).*L)./sqrt(K)/2.0+(cos(2.0*sqrt(K).*L)-1.0).*alpha0./K)./L/2.0;
    end

    function avedisp=dispfoc(disp0,dispp0,K,L)
        avedisp=(disp0.*(sin(sqrt(K).*L)./sqrt(K))+dispp0.*(1-cos(sqrt(K).*L))./K)./L;
    end
%plot(avebeta);hold all;
end
